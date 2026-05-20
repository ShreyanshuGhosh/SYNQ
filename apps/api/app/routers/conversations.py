"""Conversation REST endpoints.

Endpoints:
  POST   /conversations                        — create
  GET    /conversations                        — list (current user only)
  GET    /conversations/{id}                   — fetch with messages
  PATCH  /conversations/{id}                   — update current_model
  POST   /conversations/{id}/messages          — append user message, stream
                                                 assistant reply via SSE
  GET    /models                               — list available models

Authorization rule: rows are filtered by user_id == current_user.id. A user
can never see (or write to) another user's conversation — fetches return 404,
writes return 404, so the existence of an unrelated row is not leaked.

Idempotency: POST /messages may carry `idempotency_key`. Duplicate keys are
not double-applied (per canonical-data-model rule "Retries never duplicate
turns"); the existing message is replayed.

Phase 2 additions (no provider conditionals — all per-provider behavior
lives in app/adapters/):
  * Model switch via PATCH triggers a token-count backfill task so the
    next switch is O(1).
  * SSE stream emits `context_warning` when naive truncation drops
    older turns, and `model_switch` when identity drift is detected so
    the UI can render a "Switched to X" badge.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.adapters import adapter_for, list_models
from app.auth import AuthenticatedUser
from app.config import settings
from app.db import SessionLocal, get_session
from app.llm import token_counts_from_usage
from app.models import (
    Conversation as ConversationModel,
)
from app.models import (
    CreateConversationRequest,
    CreateConversationResponse,
    GetConversationResponse,
    ListConversationsResponse,
    SendMessageRequest,
    TextBlock,
)
from app.models import (
    Message as MessageModel,
)
from app.orchestrator import plan_turn, run_turn
from app.orm import Conversation, Message
from app.ratelimit import enforce_rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/conversations", tags=["conversations"])
models_router = APIRouter(tags=["models"])


@asynccontextmanager
async def _writer_session() -> AsyncGenerator[AsyncSession, None]:
    """Independent session for writes that happen inside the SSE generator,
    after the original request-scoped session has been released."""
    async with SessionLocal() as s:
        yield s


async def _load_owned_conversation(
    session: AsyncSession, conv_id: UUID, user_id: UUID
) -> Conversation:
    row = (
        await session.execute(
            select(Conversation).where(
                Conversation.id == conv_id,
                Conversation.user_id == user_id,
                Conversation.archived_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return row


@router.post(
    "", response_model=CreateConversationResponse, status_code=status.HTTP_201_CREATED
)
async def create_conversation(
    body: CreateConversationRequest,
    user: AuthenticatedUser = Depends(enforce_rate_limit),
    session: AsyncSession = Depends(get_session),
) -> CreateConversationResponse:
    conv = Conversation(
        user_id=user.id,
        title=body.title,
        current_model=settings.default_model,
    )
    session.add(conv)
    await session.commit()
    await session.refresh(conv)
    return CreateConversationResponse(conversation=ConversationModel.model_validate(conv))


@router.get("", response_model=ListConversationsResponse)
async def list_conversations(
    user: AuthenticatedUser = Depends(enforce_rate_limit),
    session: AsyncSession = Depends(get_session),
) -> ListConversationsResponse:
    result = await session.execute(
        select(Conversation)
        .where(Conversation.user_id == user.id, Conversation.archived_at.is_(None))
        .order_by(Conversation.updated_at.desc())
    )
    rows = list(result.scalars().all())
    return ListConversationsResponse(
        conversations=[ConversationModel.model_validate(r) for r in rows],
        total=len(rows),
    )


@router.get("/{conv_id}", response_model=GetConversationResponse)
async def get_conversation(
    conv_id: UUID,
    user: AuthenticatedUser = Depends(enforce_rate_limit),
    session: AsyncSession = Depends(get_session),
) -> GetConversationResponse:
    conv = await _load_owned_conversation(session, conv_id, user.id)
    msgs = list(
        (
            await session.execute(
                select(Message)
                .where(Message.conversation_id == conv.id)
                .order_by(Message.turn_index.asc())
            )
        )
        .scalars()
        .all()
    )
    return GetConversationResponse(
        conversation=ConversationModel.model_validate(conv),
        messages=[MessageModel.model_validate(m) for m in msgs],
    )


# ── PATCH: switch model ─────────────────────────────────────────────────


class UpdateConversationRequest(BaseModel):
    current_model: str | None = None
    title: str | None = None


@router.patch("/{conv_id}", response_model=ConversationModel)
async def update_conversation(
    conv_id: UUID,
    body: UpdateConversationRequest,
    user: AuthenticatedUser = Depends(enforce_rate_limit),
    session: AsyncSession = Depends(get_session),
) -> ConversationModel:
    """Update `current_model` (model picker) or `title`.

    Switching the model kicks off a background backfill of token counts
    for the new provider so the next switch is O(1). The backfill is
    fire-and-forget per Phase 2 spec — Phase 5 will move this onto
    Temporal/Celery.
    """
    conv = await _load_owned_conversation(session, conv_id, user.id)

    if body.title is not None:
        conv.title = body.title

    triggered_backfill = False
    if body.current_model is not None and body.current_model != conv.current_model:
        # Reject obviously unknown models up front. The adapter registry
        # falls back to Gemini for unknown ids; we'd rather 400 here than
        # silently route somewhere else.
        if body.current_model not in {m["id"] for m in list_models()}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"unknown_model: {body.current_model}",
            )
        conv.current_model = body.current_model
        triggered_backfill = True

    conv.version = (conv.version or 0) + 1
    await session.commit()
    await session.refresh(conv)

    if triggered_backfill:
        # Detach from request lifecycle. Errors are logged, never raised
        # — the PATCH must succeed even if backfill cannot.
        asyncio.create_task(_backfill_token_counts(conv.id, conv.current_model))

    return ConversationModel.model_validate(conv)


# ── Models listing ──────────────────────────────────────────────────────


class ModelListResponse(BaseModel):
    models: list[dict[str, str]]
    default: str


@models_router.get("/models", response_model=ModelListResponse)
async def list_available_models(
    _user: AuthenticatedUser = Depends(enforce_rate_limit),
) -> ModelListResponse:
    return ModelListResponse(models=list_models(), default=settings.default_model)


# ── Send message (streaming) ────────────────────────────────────────────


async def _next_turn_index(session: AsyncSession, conv_id: UUID) -> int:
    result = await session.execute(
        select(func.coalesce(func.max(Message.turn_index), -1)).where(
            Message.conversation_id == conv_id
        )
    )
    return int(result.scalar_one()) + 1


def _sse(event: str, data: dict[str, Any] | str) -> dict[str, str]:
    return {"event": event, "data": data if isinstance(data, str) else json.dumps(data)}


@router.post("/{conv_id}/messages")
async def send_message(
    conv_id: UUID,
    body: SendMessageRequest,
    user: AuthenticatedUser = Depends(enforce_rate_limit),
    session: AsyncSession = Depends(get_session),
) -> EventSourceResponse:
    conv = await _load_owned_conversation(session, conv_id, user.id)

    # ── Idempotency replay ────────────────────────────────────────────────
    if body.idempotency_key:
        existing = (
            await session.execute(
                select(Message).where(Message.idempotency_key == body.idempotency_key)
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.conversation_id != conv.id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="idempotency_key_reused_for_other_conversation",
                )
            assistant_existing = (
                await session.execute(
                    select(Message).where(
                        Message.conversation_id == conv.id,
                        Message.turn_index == existing.turn_index + 1,
                        Message.role == "assistant",
                    )
                )
            ).scalar_one_or_none()

            user_payload = MessageModel.model_validate(existing).model_dump(mode="json")
            assistant_payload = (
                MessageModel.model_validate(assistant_existing).model_dump(mode="json")
                if assistant_existing is not None
                else None
            )

            async def replay() -> AsyncIterator[dict[str, str]]:
                yield _sse("user_message", user_payload)
                if assistant_payload is not None:
                    for block in assistant_payload["content"]:
                        if block.get("type") == "text":
                            yield _sse("token", {"text": block.get("text", "")})
                    yield _sse("done", assistant_payload)
                else:
                    yield _sse("error", {"message": "interrupted_no_assistant"})

            return EventSourceResponse(replay())

    # ── Persist user turn ─────────────────────────────────────────────────
    target_model = body.model or conv.current_model or settings.default_model
    turn_index = await _next_turn_index(session, conv.id)
    user_msg = Message(
        conversation_id=conv.id,
        turn_index=turn_index,
        role="user",
        content=[b.model_dump(mode="json") for b in body.content],
        idempotency_key=body.idempotency_key,
    )
    session.add(user_msg)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"conflict: {exc.orig}"
        ) from exc
    await session.refresh(user_msg)

    # Snapshot history for the model BEFORE handing off to the generator —
    # the request session will be closed by the time the generator runs.
    history_rows = list(
        (
            await session.execute(
                select(Message)
                .where(Message.conversation_id == conv.id)
                .order_by(Message.turn_index.asc())
            )
        )
        .scalars()
        .all()
    )
    history = [MessageModel.model_validate(m) for m in history_rows]
    user_msg_payload = MessageModel.model_validate(user_msg).model_dump(mode="json")
    conv_id_local = conv.id
    next_assistant_turn = turn_index + 1

    async def event_source() -> AsyncIterator[dict[str, str]]:
        yield _sse("user_message", user_msg_payload)

        plan = await plan_turn(history, target_model)

        # Surface the planning outcome to the UI BEFORE tokens start
        # arriving. The UI uses these to render the "Switched to X"
        # badge and the "Earlier messages dropped" banner.
        if plan.drift_detected:
            yield _sse(
                "model_switch",
                {
                    "model": plan.model,
                    "provider": plan.provider,
                    "note": (
                        "Continued on a different model. Earlier responses "
                        "were generated by another provider."
                    ),
                },
            )
        if plan.truncated:
            yield _sse(
                "context_warning",
                {
                    "dropped": plan.dropped_count,
                    "message": (
                        f"Earlier messages dropped to fit context "
                        f"({plan.dropped_count} turn(s))."
                    ),
                },
            )

        # Persist the user-message token count off the hot path. The
        # SSE stream must never block on token-counter network calls
        # (Gemini's count_tokens, HF tokenizer downloads, etc.) — those
        # are slow on cold start and would freeze the assistant reply.
        asyncio.create_task(
            _cache_user_token_count(user_msg.id, history[-1], plan.adapter, plan.provider)
        )

        buffered: list[str] = []
        usage: dict[str, int] | None = None
        errored: str | None = None
        async for event in run_turn(plan):
            if event.type == "text" and isinstance(event.content, str):
                buffered.append(event.content)
                yield _sse("token", {"text": event.content})
            elif event.type == "stop":
                usage = event.usage
            elif event.type == "error":
                errored = str(event.content)
                yield _sse("error", {"message": errored})
                break

        if errored is not None:
            return

        assistant_text = "".join(buffered)
        async with _writer_session() as ws:
            assistant = Message(
                conversation_id=conv_id_local,
                turn_index=next_assistant_turn,
                role="assistant",
                content=[TextBlock(text=assistant_text).model_dump(mode="json")],
                model_used=target_model,
                token_counts=token_counts_from_usage(target_model, usage),
            )
            ws.add(assistant)
            conv_row = await ws.get(Conversation, conv_id_local)
            if conv_row is not None:
                conv_row.version = (conv_row.version or 0) + 1
                conv_row.current_model = target_model
            await ws.commit()
            await ws.refresh(assistant)
            yield _sse(
                "done",
                MessageModel.model_validate(assistant).model_dump(mode="json"),
            )

    return EventSourceResponse(event_source())


# ── Token-count backfill (fire-and-forget) ──────────────────────────────


async def _cache_user_token_count(
    msg_id: UUID,
    msg: MessageModel,
    adapter: Any,
    provider: str,
) -> None:
    """Compute and cache the token count for one user message.

    Runs detached from the SSE generator so the user never waits on a
    cold tokenizer download. Best-effort: failures are logged, not raised.
    """
    try:
        n = await adapter.count_tokens([msg])
        async with SessionLocal() as ws:
            row = await ws.get(Message, msg_id)
            if row is None:
                return
            counts = dict(row.token_counts or {})
            counts[provider] = n
            row.token_counts = counts
            await ws.commit()
    except Exception:
        logger.exception("token-count cache write failed for user msg %s", msg_id)


async def _backfill_token_counts(conv_id: UUID, model: str | None) -> None:
    """Compute token counts for every message under `model`'s provider.

    Runs as a background task after PATCH /conversations/{id} flips the
    model. Idempotent: only writes when the per-provider slot is empty.
    Errors are swallowed (logged) — backfill is opportunistic.
    """
    if not model:
        return
    adapter = adapter_for(model)
    provider = adapter.provider
    try:
        async with SessionLocal() as ws:
            rows = list(
                (
                    await ws.execute(
                        select(Message)
                        .where(Message.conversation_id == conv_id)
                        .order_by(Message.turn_index.asc())
                    )
                )
                .scalars()
                .all()
            )
            for row in rows:
                counts = dict(row.token_counts or {})
                if provider in counts:
                    continue
                msg = MessageModel.model_validate(row)
                try:
                    counts[provider] = await adapter.count_tokens([msg])
                except Exception:
                    logger.warning(
                        "backfill: token count failed for msg=%s provider=%s",
                        row.id,
                        provider,
                    )
                    continue
                row.token_counts = counts
            await ws.commit()
            logger.info(
                "backfill: token counts updated for conv=%s provider=%s",
                conv_id,
                provider,
            )
    except Exception:
        logger.exception("backfill task failed for conv=%s model=%s", conv_id, model)
