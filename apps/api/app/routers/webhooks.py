"""Clerk webhooks — user lifecycle events.

We listen for `user.created` and `user.deleted`. The user row is created
here on first sign-in; the auth dependency also lazy-creates it as a fallback
in case the webhook is delayed.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import verify_clerk_webhook
from app.db import get_session
from app.orm import User

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/clerk", status_code=status.HTTP_200_OK)
async def clerk_webhook(
    session: AsyncSession = Depends(get_session),
    event: dict = Depends(verify_clerk_webhook),  # type: ignore[type-arg]
) -> dict[str, str]:
    event_type = event.get("type")
    data = event.get("data", {}) or {}
    clerk_id = data.get("id")
    if not clerk_id:
        return {"status": "ignored"}

    if event_type == "user.created":
        existing = (
            await session.execute(select(User).where(User.clerk_id == clerk_id))
        ).scalar_one_or_none()
        if existing is None:
            email = None
            emails = data.get("email_addresses") or []
            if emails:
                email = emails[0].get("email_address")
            session.add(User(clerk_id=clerk_id, email=email))
            await session.commit()
        return {"status": "created"}

    if event_type == "user.deleted":
        await session.execute(delete(User).where(User.clerk_id == clerk_id))
        await session.commit()
        return {"status": "deleted"}

    return {"status": "ignored"}
