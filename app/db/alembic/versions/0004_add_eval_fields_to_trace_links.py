"""Add eval fields to trace_links — eval report feature.

New columns on trace_links:
  milestone_id — optional coding MilestoneItem.id this link belongs to
  eval_type    — "unit" | "integration" | "e2e" | "contract" | "manual"
  source       — "manual" | "auto" (how the link was created)

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-04
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("trace_links", sa.Column("milestone_id", sa.String(100), nullable=True))
    op.add_column("trace_links", sa.Column("eval_type", sa.String(50), nullable=True))
    op.add_column(
        "trace_links",
        sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
    )
    op.create_index("ix_trace_links_milestone_id", "trace_links", ["milestone_id"])


def downgrade() -> None:
    op.drop_index("ix_trace_links_milestone_id", table_name="trace_links")
    op.drop_column("trace_links", "source")
    op.drop_column("trace_links", "eval_type")
    op.drop_column("trace_links", "milestone_id")
