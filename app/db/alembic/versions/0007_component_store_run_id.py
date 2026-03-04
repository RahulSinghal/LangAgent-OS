"""Add run_id to component_store for revision tracking.

Revision ID: 0007
Revises: 0006
Create Date: 2026-03-04

When a project is revised (e.g. PRD v2 after a few months) and reaches
completion again, end_node replaces all auto-extracted components for
that project with the latest SoT content.  run_id records which run
produced each component row, making it easy to audit which version of
the project the knowledge came from.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "component_store",
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_component_store_run_id", "component_store", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_component_store_run_id", table_name="component_store")
    op.drop_column("component_store", "run_id")
