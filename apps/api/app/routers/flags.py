"""Feature flag introspection endpoint.

GET /api/flags returns the current state of every registered flag so the
dashboard can display them. Auth: behind the same Clerk + rate limiter
gate as the rest of the dashboard endpoints — never exposed unauthed.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.auth import AuthenticatedUser
from app.core.flags import all_flags
from app.ratelimit import enforce_rate_limit


router = APIRouter(tags=["flags"])


@router.get("/api/flags")
async def get_flags(
    _u: AuthenticatedUser = Depends(enforce_rate_limit),
) -> dict[str, Any]:
    return {"flags": all_flags()}
