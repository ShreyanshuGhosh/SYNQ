"""phase 3 — extend files table for the multimodal pipeline.

Revision ID: 0002_phase3_files
Revises: 0001_initial
Create Date: 2026-05-21

The base ``files`` table from 0001 already carries every column called
out in SYNQ_STRUCT §"Canonical Data Model". Phase 3 adds three things
on top:

  * ``original_filename`` — preserved verbatim for chip rendering in the
    UI (storage_url itself uses a UUID key so it stays opaque).
  * ``error`` — JSONB error payload populated by the parse worker when
    parse_status flips to 'failed'. Read by the chat UI to show a red
    chip with the failure reason.
  * ``conversation_id`` (nullable) — optional back-link from a file to
    the conversation it was uploaded into. Files can exist before being
    attached to any conversation (paste-then-cancel flow), so the column
    is nullable and not part of any UNIQUE constraint.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_phase3_files"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "files",
        sa.Column("original_filename", sa.Text(), nullable=True),
    )
    op.add_column(
        "files",
        sa.Column(
            "error", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )
    op.add_column(
        "files",
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_files_conversation_id", "files", ["conversation_id"])


def downgrade() -> None:
    op.drop_index("ix_files_conversation_id", table_name="files")
    op.drop_column("files", "conversation_id")
    op.drop_column("files", "error")
    op.drop_column("files", "original_filename")
