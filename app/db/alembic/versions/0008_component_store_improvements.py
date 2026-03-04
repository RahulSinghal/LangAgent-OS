"""Add content_hash and source index to component_store.

Revision ID: 0008
Revises: 0007
Create Date: 2026-03-04

content_hash: SHA-256 fingerprint (component_type + normalised content).
  Non-unique — each project stores its own rows so per-project purge
  works correctly.  Deduplication happens at retrieval time: if multiple
  projects stored the same content, only the best-scoring instance is
  returned.

ix_component_store_source: index on the source column to make
  list_components(source='manual') and purge_auto_components() faster.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "component_store",
        sa.Column("content_hash", sa.String(64), nullable=True),
    )
    op.create_index(
        "ix_component_store_content_hash", "component_store", ["content_hash"]
    )
    op.create_index(
        "ix_component_store_source", "component_store", ["source"]
    )


def downgrade() -> None:
    op.drop_index("ix_component_store_source", table_name="component_store")
    op.drop_index("ix_component_store_content_hash", table_name="component_store")
    op.drop_column("component_store", "content_hash")
