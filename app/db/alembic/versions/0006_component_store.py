"""Add component_store table for cross-project memory.

Revision ID: 0006
Revises: 0005
Create Date: 2026-03-04
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "component_store",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "source_project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("component_type", sa.String(60), nullable=False),
        sa.Column("category", sa.String(100), nullable=False, server_default="general"),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tags_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("source", sa.String(20), nullable=False, server_default="auto"),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_component_store_component_type", "component_store", ["component_type"])
    op.create_index("ix_component_store_category", "component_store", ["category"])


def downgrade() -> None:
    op.drop_index("ix_component_store_category", table_name="component_store")
    op.drop_index("ix_component_store_component_type", table_name="component_store")
    op.drop_table("component_store")
