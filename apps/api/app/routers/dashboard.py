"""Personal-use dashboard API.

Six panels (per Phase 5 spec). Each panel runs a single SQL query
against the ``usage_events`` table in Postgres (no ClickHouse — Postgres
is sufficient at personal scale). Three additional helper endpoints
expose router + health + limit state.

Auth: every endpoint uses the existing Clerk auth + rate limiter. No
extra role check is needed — there is only one user in personal mode.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthenticatedUser
from app.config import settings
from app.db import get_session
from app.ratelimit import enforce_rate_limit
from app.router.health_probes import read_all_health
from app.router.provider_router import get_chain
from app.workers.cost_meter import (
    PRICE_TABLE,
    is_daily_warning_active_sync,
    is_hard_limit_exceeded_sync,
)

logger = logging.getLogger(__name__)


router = APIRouter(tags=["dashboard"])


# ── Router introspection (Panel header / Settings) ──────────────────────


@router.get("/api/router/chain")
async def get_router_chain(
    _u: AuthenticatedUser = Depends(enforce_rate_limit),
) -> dict[str, Any]:
    return {
        "chain": get_chain(),
        "cost_aware_routing": settings.cost_aware_routing,
        "cost_aware_prompt_threshold": settings.cost_aware_prompt_threshold,
    }


@router.get("/api/health/providers")
async def get_provider_health(
    _u: AuthenticatedUser = Depends(enforce_rate_limit),
) -> dict[str, Any]:
    return {"providers": await read_all_health()}


@router.get("/api/config/limits")
async def get_limits(
    _u: AuthenticatedUser = Depends(enforce_rate_limit),
) -> dict[str, Any]:
    blocked, today_usd, hard_limit = is_hard_limit_exceeded_sync()
    return {
        "daily_soft_limit_usd": settings.daily_soft_limit_usd,
        "hard_daily_limit_usd": hard_limit,
        "today_usd_estimate": round(today_usd, 4),
        "hard_limit_blocked": blocked,
        "soft_warning_active": is_daily_warning_active_sync(),
        "price_table_models": sorted(PRICE_TABLE.keys()),
    }


# ── Panel A — today's stats ─────────────────────────────────────────────


@router.get("/api/usage/stats/today")
async def stats_today(
    _u: AuthenticatedUser = Depends(enforce_rate_limit),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    result = await session.execute(
        text(
            """
            SELECT
                COALESCE(ROUND(SUM(cost_usd)::numeric, 4), 0) AS today_cost_usd,
                COUNT(*)                                       AS turns_today,
                COUNT(*) FILTER (WHERE was_fallback)           AS fallbacks_today,
                COUNT(*) FILTER (WHERE
                    fallback_reason = 'manual_switch'
                )                                              AS manual_switches_today
            FROM usage_events
            WHERE ts >= NOW() - INTERVAL '1 day'
            """
        )
    )
    row = result.mappings().one()
    return {
        "today_cost_usd": float(row["today_cost_usd"] or 0),
        "turns_today": int(row["turns_today"] or 0),
        "fallbacks_today": int(row["fallbacks_today"] or 0),
        "manual_switches_today": int(row["manual_switches_today"] or 0),
        "daily_soft_limit_usd": settings.daily_soft_limit_usd,
    }


# ── Panel B — daily cost (30 days) ──────────────────────────────────────


@router.get("/api/usage/daily")
async def daily_cost(
    days: int = 30,
    _u: AuthenticatedUser = Depends(enforce_rate_limit),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    days = max(1, min(days, 365))
    result = await session.execute(
        text(
            f"""
            SELECT
                DATE_TRUNC('day', ts)                         AS day,
                ROUND(SUM(cost_usd)::numeric, 4)              AS cost_usd,
                SUM(prompt_tokens + completion_tokens)         AS total_tokens
            FROM usage_events
            WHERE ts >= NOW() - INTERVAL '{days} days'
            GROUP BY 1
            ORDER BY 1
            """
        )
    )
    rows = [
        {
            "day": r["day"].isoformat() if r["day"] else None,
            "cost_usd": float(r["cost_usd"] or 0),
            "total_tokens": int(r["total_tokens"] or 0),
        }
        for r in result.mappings().all()
    ]
    return {"days": rows, "daily_soft_limit_usd": settings.daily_soft_limit_usd}


# ── Panel C — provider donut (this month) ───────────────────────────────


@router.get("/api/usage/providers/month")
async def providers_month(
    _u: AuthenticatedUser = Depends(enforce_rate_limit),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    result = await session.execute(
        text(
            """
            SELECT
                provider,
                ROUND(SUM(cost_usd)::numeric, 4)                          AS cost_usd,
                ROUND(100.0 * SUM(cost_usd) /
                    NULLIF(SUM(SUM(cost_usd)) OVER (), 0), 1)            AS pct,
                COUNT(*)                                                  AS turns
            FROM usage_events
            WHERE ts >= DATE_TRUNC('month', NOW())
            GROUP BY provider
            ORDER BY cost_usd DESC NULLS LAST
            """
        )
    )
    rows = [
        {
            "provider": r["provider"] or "unknown",
            "cost_usd": float(r["cost_usd"] or 0),
            "pct": float(r["pct"] or 0),
            "turns": int(r["turns"] or 0),
        }
        for r in result.mappings().all()
    ]
    return {"providers": rows}


# ── Panel E — recent fallbacks ──────────────────────────────────────────


@router.get("/api/usage/fallbacks")
async def recent_fallbacks(
    limit: int = 20,
    _u: AuthenticatedUser = Depends(enforce_rate_limit),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    limit = max(1, min(limit, 100))
    result = await session.execute(
        text(
            f"""
            SELECT
                ts,
                fallback_from,
                provider AS fallback_to,
                fallback_reason,
                conversation_id,
                latency_ms
            FROM usage_events
            WHERE was_fallback = TRUE
            ORDER BY ts DESC
            LIMIT {limit}
            """
        )
    )
    rows = [
        {
            "ts": r["ts"].isoformat() if r["ts"] else None,
            "fallback_from": r["fallback_from"],
            "fallback_to": r["fallback_to"],
            "fallback_reason": r["fallback_reason"],
            "conversation_id": str(r["conversation_id"]) if r["conversation_id"] else None,
            "latency_ms": r["latency_ms"],
        }
        for r in result.mappings().all()
    ]
    return {"fallbacks": rows}


# ── Panel F — hourly tokens (7 days) ────────────────────────────────────


@router.get("/api/usage/tokens")
async def hourly_tokens(
    hours: int = 168,
    _u: AuthenticatedUser = Depends(enforce_rate_limit),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    hours = max(1, min(hours, 720))
    result = await session.execute(
        text(
            f"""
            SELECT
                DATE_TRUNC('hour', ts)  AS hour,
                SUM(prompt_tokens)      AS prompt,
                SUM(completion_tokens)  AS completion
            FROM usage_events
            WHERE ts >= NOW() - INTERVAL '{hours} hours'
            GROUP BY 1
            ORDER BY 1
            """
        )
    )
    rows = [
        {
            "hour": r["hour"].isoformat() if r["hour"] else None,
            "prompt": int(r["prompt"] or 0),
            "completion": int(r["completion"] or 0),
        }
        for r in result.mappings().all()
    ]
    return {"hours": rows}
