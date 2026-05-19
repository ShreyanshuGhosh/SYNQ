"""Basic per-user fixed-window rate limiter backed by Redis.

Phase 1: 60 requests / minute / user. Phase 5 replaces this with token-bucket
limits keyed on messages/tokens/cost. Returns HTTP 429 with Retry-After.
"""

from __future__ import annotations

import redis.asyncio as redis
from fastapi import Depends, HTTPException, Response, status

from app.auth import AuthenticatedUser, current_user
from app.config import settings

_redis: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def enforce_rate_limit(
    response: Response,
    user: AuthenticatedUser = Depends(current_user),
) -> AuthenticatedUser:
    r = get_redis()
    bucket_key = f"ratelimit:{user.id}:minute"
    count = await r.incr(bucket_key)
    if count == 1:
        await r.expire(bucket_key, 60)
    if count > settings.rate_limit_per_minute:
        ttl = await r.ttl(bucket_key)
        retry_after = max(ttl, 1)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate_limit_exceeded",
            headers={"Retry-After": str(retry_after)},
        )
    response.headers["X-RateLimit-Limit"] = str(settings.rate_limit_per_minute)
    response.headers["X-RateLimit-Remaining"] = str(
        max(settings.rate_limit_per_minute - count, 0)
    )
    return user
