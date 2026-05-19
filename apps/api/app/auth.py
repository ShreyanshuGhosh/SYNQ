"""Clerk JWT verification + webhook signature verification.

The `current_user` dependency:
  1. Pulls the bearer token from the Authorization header.
  2. Verifies the signature using Clerk's JWKS (cached for 10 min).
  3. Looks up — or lazily creates — the matching row in `users` and returns
     its internal UUID so downstream code never deals with Clerk's string IDs.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from jwt import PyJWKClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.orm import User

_jwks_client: PyJWKClient | None = None
_jwks_client_created_at: float = 0.0
_JWKS_TTL_SECONDS = 600


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client, _jwks_client_created_at
    now = time.time()
    if _jwks_client is None or (now - _jwks_client_created_at) > _JWKS_TTL_SECONDS:
        if not settings.clerk_jwks_url:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="CLERK_JWKS_URL not configured",
            )
        _jwks_client = PyJWKClient(settings.clerk_jwks_url, cache_keys=True)
        _jwks_client_created_at = now
    return _jwks_client


@dataclass
class AuthenticatedUser:
    id: UUID
    clerk_id: str
    email: str | None


async def _verify_clerk_token(token: str) -> dict[str, Any]:
    try:
        client = _get_jwks_client()
        signing_key = client.get_signing_key_from_jwt(token)
        return jwt.decode(  # type: ignore[no-any-return]
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=settings.clerk_issuer or None,
            options={"verify_aud": False},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid Clerk token: {exc}",
        ) from exc


async def current_user(
    request: Request,
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> AuthenticatedUser:
    # Accept either Authorization: Bearer <jwt> or a __session cookie.
    token: str | None = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    elif "__session" in request.cookies:
        token = request.cookies["__session"]
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )

    claims = await _verify_clerk_token(token)
    clerk_id = claims.get("sub")
    if not clerk_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing sub"
        )

    user = (
        await session.execute(select(User).where(User.clerk_id == clerk_id))
    ).scalar_one_or_none()
    if user is None:
        # First request before webhook fired — lazy-create. Concurrent
        # initial requests race here; treat UNIQUE violation as a tie and
        # re-select the row the winner created.
        from sqlalchemy.exc import IntegrityError

        email = claims.get("email") or claims.get("email_address")
        user = User(clerk_id=clerk_id, email=email)
        session.add(user)
        try:
            await session.commit()
            await session.refresh(user)
        except IntegrityError:
            await session.rollback()
            user = (
                await session.execute(
                    select(User).where(User.clerk_id == clerk_id)
                )
            ).scalar_one()

    return AuthenticatedUser(id=user.id, clerk_id=user.clerk_id, email=user.email)


async def verify_clerk_webhook(request: Request) -> dict[str, Any]:
    """Verify a Clerk webhook signature via Svix headers and return parsed body."""
    from svix.webhooks import Webhook, WebhookVerificationError

    if not settings.clerk_webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="CLERK_WEBHOOK_SECRET not configured",
        )

    body = await request.body()
    headers = {
        "svix-id": request.headers.get("svix-id", ""),
        "svix-timestamp": request.headers.get("svix-timestamp", ""),
        "svix-signature": request.headers.get("svix-signature", ""),
    }
    try:
        wh = Webhook(settings.clerk_webhook_secret)
        return wh.verify(body, headers)  # type: ignore[no-any-return]
    except WebhookVerificationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid webhook signature: {exc}",
        ) from exc
