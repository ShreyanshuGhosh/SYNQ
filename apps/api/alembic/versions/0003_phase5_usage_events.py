"""phase 5 — usage_events table for personal-use cost meter & dashboard.

Revision ID: 0003_phase5_usage_events
Revises: 0002_phase3_files
Create Date: 2026-05-26

Personal-use SaaS — single user, no multi-tenant billing. usage_events is
the analytic source of truth for the /dashboard panels. We keep it in
Postgres rather than ClickHouse because at personal scale (a few hundred
turns/day max) Postgres handles the aggregations trivially and we avoid
running another service.

The ``message_id`` UNIQUE constraint is what makes the cost meter task
idempotent: a Celery retry of meter_usage(message_id) will hit the
UNIQUE and be a no-op via INSERT ... ON CONFLICT DO NOTHING.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_phase5_usage_events"
down_revision: str | None = "0002_phase3_files"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "usage_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=True),
        sa.Column(
            "was_fallback",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("fallback_reason", sa.Text(), nullable=True),
        sa.Column("fallback_from", sa.Text(), nullable=True),
        sa.Column(
            "compression_used",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("rag_chunks_retrieved", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.UniqueConstraint("message_id", name="uq_usage_events_message_id"),
    )
    op.create_index("ix_usage_events_ts_desc", "usage_events", [sa.text("ts DESC")])
    op.create_index(
        "ix_usage_events_provider_ts",
        "usage_events",
        ["provider", sa.text("ts DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_usage_events_provider_ts", table_name="usage_events")
    op.drop_index("ix_usage_events_ts_desc", table_name="usage_events")
    op.drop_table("usage_events")
