"""Conversation REST endpoints.

Endpoints:
  POST   /conversations                        — create
  GET    /conversations                        — list (current user only)
  GET    /conversations/{id}                   — fetch with messages
  POST   /conversations/{id}/messages          — append user message, stream
                                                 assistant reply via SSE

Authorization rule: rows are filtered by user_id == current_user.id. A user
can never see (or write to) another user's conversation — fetches return 404,
writes return 404, so the existence of an unrelated row is not leaked.

Idempotency: POST /messages may carry `idempotency_key`. Duplicate keys are
not double-applied (per canonical-data-model rule "Retries never duplicate
turns"); the existing message is replayed.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.auth import AuthenticatedUser
from app.config import settings
from app.db import SessionLocal, get_session
from app.llm import stream_completion, token_counts_from_usage
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
from app.orm import Conversation, Message
from app.ratelimit import enforce_rate_limit

router = APIRouter(prefix="/conversations", tags=["conversations"])


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
    target_model = body.model or conv.current_model or settings.default_model
    conv_id_local = conv.id
    next_assistant_turn = turn_index + 1

    async def event_source() -> AsyncIterator[dict[str, str]]:
        yield _sse("user_message", user_msg_payload)

        buffered: list[str] = []
        usage: dict[str, int] | None = None
        errored: str | None = None
        async for event in stream_completion(history, model=target_model):
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
