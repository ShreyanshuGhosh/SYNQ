"""Resolve every file_id in a message history to a ResolvedFile.

Called by the orchestrator AFTER identity-drift handling and BEFORE the
adapter translates messages to wire format. The output is a dict
``{file_id: ResolvedFile}`` that adapters consult when emitting
provider-native blocks.

The resolution itself is delegated to the adapter so each provider can
override the strategy (Gemini, for example, prefers the Files API for
images). This module's job is just:

  1. Collect every file_id referenced in the history.
  2. Authorization-check that each row's user_id matches the requesting
     user (a stolen file_id from another user would otherwise leak).
  3. Hand each row to ``adapter.resolve_file``.
  4. Return the lookup map.

The orchestrator + adapters then turn ImageBlock / FileRefBlock entries
into provider-native blocks using this map.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select

from app.adapters.base import ProviderAdapter, ResolvedFile
from app.db import SessionLocal
from app.models import FileRefBlock, ImageBlock, Message
from app.orm import File

logger = logging.getLogger(__name__)


def collect_file_ids(messages: list[Message]) -> list[UUID]:
    """Every UUID referenced from `messages.content` blocks, deduped."""
    seen: dict[UUID, None] = {}
    for m in messages:
        for block in m.content:
            if isinstance(block, (ImageBlock, FileRefBlock)):
                seen.setdefault(block.file_id, None)
    return list(seen.keys())


async def resolve_files_for_turn(
    messages: list[Message],
    adapter: ProviderAdapter,
    user_id: UUID | None = None,
) -> dict[str, ResolvedFile]:
    """Resolve every file referenced in `messages` for `adapter`'s provider.

    `user_id` is used for the authorization check. When ``None`` (e.g.
    the replay tool which runs locally as the developer) the check is
    skipped — never call with user_id=None from a request path.
    """
    file_ids = collect_file_ids(messages)
    if not file_ids:
        return {}

    async with SessionLocal() as session:
        rows = list(
            (
                await session.execute(select(File).where(File.id.in_(file_ids)))
            )
            .scalars()
            .all()
        )

    by_id: dict[UUID, File] = {r.id: r for r in rows}
    out: dict[str, ResolvedFile] = {}
    for fid in file_ids:
        row = by_id.get(fid)
        if row is None:
            logger.warning("resolve: file_id=%s not found, skipping", fid)
            continue
        if user_id is not None and row.user_id != user_id:
            logger.warning(
                "resolve: file_id=%s belongs to user %s, not %s; skipping",
                fid, row.user_id, user_id,
            )
            continue
        out[str(fid)] = await adapter.resolve_file(row)
    return out
