"""Phase 3 governance tables — multi-tenant, policy engine, observability.

New tables:
  organizations, users, project_org_map, policies,
  baseline_snapshots, change_requests, provenance_links,
  audit_logs, artifact_comments, artifact_lint_reports,
  run_metrics

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-01
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── organizations ─────────────────────────────────────────────────────────
    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("plan", sa.String(50), nullable=False, server_default="free"),
        sa.Column("settings_jsonb", JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_organizations_slug", "organizations", ["slug"])

    # ── users ─────────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=True),
        sa.Column("role", sa.String(50), nullable=False, server_default="viewer"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_org_id", "users", ["org_id"])
    op.create_index("ix_users_email", "users", ["email"])

    # ── project_org_map ───────────────────────────────────────────────────────
    op.create_table(
        "project_org_map",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_project_org_map_project_id", "project_org_map", ["project_id"])
    op.create_index("ix_project_org_map_org_id", "project_org_map", ["org_id"])

    # ── policies ──────────────────────────────────────────────────────────────
    op.create_table(
        "policies",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("policy_type", sa.String(100), nullable=False),
        sa.Column("rules_jsonb", JSONB(), nullable=False, server_default="{}"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_policies_org_id", "policies", ["org_id"])

    # ── baseline_snapshots ────────────────────────────────────────────────────
    op.create_table(
        "baseline_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("source_snapshot_id", sa.Integer(), nullable=True),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("state_jsonb", JSONB(), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_baseline_snapshots_project_id", "baseline_snapshots", ["project_id"])
    op.create_index("ix_baseline_snapshots_run_id", "baseline_snapshots", ["run_id"])

    # ── change_requests ───────────────────────────────────────────────────────
    op.create_table(
        "change_requests",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("baseline_id", sa.Integer(), nullable=True),
        sa.Column("diff_jsonb", JSONB(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(30), nullable=False, server_default="open"),
        sa.Column("requested_by", sa.String(255), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["baseline_id"], ["baseline_snapshots.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_change_requests_project_id", "change_requests", ["project_id"])
    op.create_index("ix_change_requests_baseline_id", "change_requests", ["baseline_id"])

    # ── provenance_links ──────────────────────────────────────────────────────
    op.create_table(
        "provenance_links",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("artifact_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("sot_field", sa.String(255), nullable=False),
        sa.Column("source_node", sa.String(100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_provenance_links_artifact_id", "provenance_links", ["artifact_id"])
    op.create_index("ix_provenance_links_run_id", "provenance_links", ["run_id"])

    # ── audit_logs ────────────────────────────────────────────────────────────
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("actor", sa.String(255), nullable=False, server_default="system"),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("detail_jsonb", JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_org_id", "audit_logs", ["org_id"])
    op.create_index("ix_audit_logs_project_id", "audit_logs", ["project_id"])
    op.create_index("ix_audit_logs_run_id", "audit_logs", ["run_id"])
    op.create_index("ix_audit_logs_event_type", "audit_logs", ["event_type"])

    # ── artifact_comments ─────────────────────────────────────────────────────
    op.create_table(
        "artifact_comments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("artifact_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("section", sa.String(255), nullable=True),
        sa.Column("author", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_artifact_comments_artifact_id", "artifact_comments", ["artifact_id"])
    op.create_index("ix_artifact_comments_project_id", "artifact_comments", ["project_id"])

    # ── artifact_lint_reports ─────────────────────────────────────────────────
    op.create_table(
        "artifact_lint_reports",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("artifact_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("findings_jsonb", JSONB(), nullable=False, server_default="[]"),
        sa.Column("severity_counts_jsonb", JSONB(), nullable=False, server_default="{}"),
        sa.Column("passed", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_artifact_lint_reports_artifact_id", "artifact_lint_reports", ["artifact_id"]
    )
    op.create_index(
        "ix_artifact_lint_reports_run_id", "artifact_lint_reports", ["run_id"]
    )

    # ── run_metrics ───────────────────────────────────────────────────────────
    op.create_table(
        "run_metrics",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_cost_usd", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("total_latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("node_metrics_jsonb", JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id"),
    )
    op.create_index("ix_run_metrics_run_id", "run_metrics", ["run_id"])
    op.create_index("ix_run_metrics_project_id", "run_metrics", ["project_id"])


def downgrade() -> None:
    # Drop in reverse dependency order
    op.drop_index("ix_run_metrics_project_id",       table_name="run_metrics")
    op.drop_index("ix_run_metrics_run_id",            table_name="run_metrics")
    op.drop_table("run_metrics")

    op.drop_index("ix_artifact_lint_reports_run_id",      table_name="artifact_lint_reports")
    op.drop_index("ix_artifact_lint_reports_artifact_id", table_name="artifact_lint_reports")
    op.drop_table("artifact_lint_reports")

    op.drop_index("ix_artifact_comments_project_id",  table_name="artifact_comments")
    op.drop_index("ix_artifact_comments_artifact_id", table_name="artifact_comments")
    op.drop_table("artifact_comments")

    op.drop_index("ix_audit_logs_event_type", table_name="audit_logs")
    op.drop_index("ix_audit_logs_run_id",     table_name="audit_logs")
    op.drop_index("ix_audit_logs_project_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_org_id",     table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_index("ix_provenance_links_run_id",      table_name="provenance_links")
    op.drop_index("ix_provenance_links_artifact_id", table_name="provenance_links")
    op.drop_table("provenance_links")

    op.drop_index("ix_change_requests_baseline_id", table_name="change_requests")
    op.drop_index("ix_change_requests_project_id",  table_name="change_requests")
    op.drop_table("change_requests")

    op.drop_index("ix_baseline_snapshots_run_id",     table_name="baseline_snapshots")
    op.drop_index("ix_baseline_snapshots_project_id", table_name="baseline_snapshots")
    op.drop_table("baseline_snapshots")

    op.drop_index("ix_policies_org_id", table_name="policies")
    op.drop_table("policies")

    op.drop_index("ix_project_org_map_org_id",     table_name="project_org_map")
    op.drop_index("ix_project_org_map_project_id", table_name="project_org_map")
    op.drop_table("project_org_map")

    op.drop_index("ix_users_email",  table_name="users")
    op.drop_index("ix_users_org_id", table_name="users")
    op.drop_table("users")

    op.drop_index("ix_organizations_slug", table_name="organizations")
    op.drop_table("organizations")
