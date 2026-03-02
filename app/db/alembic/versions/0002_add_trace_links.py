"""Add trace_links table — Phase 2.

Implements the traceability matrix linking SoT requirement IDs to test IDs.

Revision ID: 0002
Revises: 0001
Create Date: 2026-02-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "trace_links",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("requirement_id", sa.String(100), nullable=False),
        sa.Column("test_id", sa.String(100), nullable=False),
        sa.Column("link_type", sa.String(50), nullable=False, server_default="test"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trace_links_project_id",    "trace_links", ["project_id"])
    op.create_index("ix_trace_links_requirement_id", "trace_links", ["requirement_id"])
    op.create_index("ix_trace_links_test_id",        "trace_links", ["test_id"])


def downgrade() -> None:
    op.drop_index("ix_trace_links_test_id",        table_name="trace_links")
    op.drop_index("ix_trace_links_requirement_id", table_name="trace_links")
    op.drop_index("ix_trace_links_project_id",     table_name="trace_links")
    op.drop_table("trace_links")
