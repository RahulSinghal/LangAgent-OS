"""Add last_run_status to trace_links.

Revision ID: 0005
Revises: 0004
Create Date: 2026-03-04
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # "pass" | "fail" | "skip" | None
    op.add_column("trace_links", sa.Column("last_run_status", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("trace_links", "last_run_status")
