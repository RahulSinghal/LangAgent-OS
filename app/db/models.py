"""SQLAlchemy ORM models — Phase 1B → Phase 3.

Tables (Phase 1):
  projects, sessions, messages, runs, run_steps,
  snapshots, artifacts, approvals, tool_calls

Phase 2 additions:
  trace_links

Phase 3 additions:
  organizations, users, project_org_map, policies,
  baseline_snapshots, change_requests, provenance_links,
  audit_logs, artifact_comments, artifact_lint_reports,
  run_metrics
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


# ── Projects ──────────────────────────────────────────────────────────────────

class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    sessions: Mapped[list["Session"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    runs: Mapped[list["Run"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    artifacts: Mapped[list["Artifact"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    approvals: Mapped[list["Approval"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    trace_links: Mapped[list["TraceLink"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    # Phase 3 relationships
    org_maps: Mapped[list["ProjectOrgMap"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    baseline_snapshots: Mapped[list["BaselineSnapshot"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    change_requests: Mapped[list["ChangeRequest"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(
        back_populates="project"
    )

    def __repr__(self) -> str:
        return f"<Project id={self.id} name={self.name!r}>"


# ── Sessions ──────────────────────────────────────────────────────────────────

class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel: Mapped[str] = mapped_column(String(50), nullable=False, default="api")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    project: Mapped[Project] = relationship(back_populates="sessions")
    messages: Mapped[list[Message]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )
    runs: Mapped[list[Run]] = relationship(back_populates="session")

    def __repr__(self) -> str:
        return f"<Session id={self.id} project_id={self.project_id}>"


# ── Messages ──────────────────────────────────────────────────────────────────

class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    # role: "user" | "assistant" | "system"
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    session: Mapped[Session] = relationship(back_populates="messages")

    def __repr__(self) -> str:
        return f"<Message id={self.id} role={self.role!r}>"


# ── Runs ──────────────────────────────────────────────────────────────────────

class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # status: pending | running | waiting_user | waiting_approval | completed | failed
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    current_node: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    project: Mapped[Project] = relationship(back_populates="runs")
    session: Mapped[Session | None] = relationship(back_populates="runs")
    steps: Mapped[list[RunStep]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        foreign_keys="RunStep.run_id",
    )
    snapshots: Mapped[list[Snapshot]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    tool_calls: Mapped[list[ToolCall]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    approvals: Mapped[list[Approval]] = relationship(back_populates="run")
    # Phase 3 relationships
    metrics: Mapped["RunMetrics | None"] = relationship(
        back_populates="run", uselist=False, cascade="all, delete-orphan"
    )
    provenance_links: Mapped[list["ProvenanceLink"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="run")

    def __repr__(self) -> str:
        return f"<Run id={self.id} status={self.status!r} node={self.current_node!r}>"


# ── Snapshots ─────────────────────────────────────────────────────────────────
# Defined before RunStep to avoid ambiguous forward-reference issues.

class Snapshot(Base):
    __tablename__ = "snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # step_id is a soft reference (plain int, no FK) to break the circular
    # dependency: snapshots.step_id <-> run_steps.input/output_snapshot_id
    step_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    state_jsonb: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run: Mapped[Run] = relationship(back_populates="snapshots")

    def __repr__(self) -> str:
        return f"<Snapshot id={self.id} run_id={self.run_id}>"


# ── RunSteps ──────────────────────────────────────────────────────────────────

class RunStep(Base):
    __tablename__ = "run_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    node_name: Mapped[str] = mapped_column(String(100), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Soft references — plain ints to avoid circular FK with snapshots.step_id
    input_snapshot_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_snapshot_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    run: Mapped[Run] = relationship(back_populates="steps", foreign_keys=[run_id])

    def __repr__(self) -> str:
        return f"<RunStep id={self.id} node={self.node_name!r}>"


# ── Artifacts ─────────────────────────────────────────────────────────────────

class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # type: "prd" | "sow" | "change_request"
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Soft reference — snapshot this artifact was derived from
    derived_from_snapshot_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    project: Mapped[Project] = relationship(back_populates="artifacts")
    # Phase 3 relationships
    comments: Mapped[list["ArtifactComment"]] = relationship(
        back_populates="artifact", cascade="all, delete-orphan"
    )
    lint_reports: Mapped[list["ArtifactLintReport"]] = relationship(
        back_populates="artifact", cascade="all, delete-orphan"
    )
    provenance_links: Mapped[list["ProvenanceLink"]] = relationship(
        back_populates="artifact", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Artifact id={self.id} type={self.type!r} v{self.version}>"


# ── Approvals ─────────────────────────────────────────────────────────────────

class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # type: "prd" | "sow"
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    # status: "pending" | "approved" | "rejected"
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    requested_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    comments: Mapped[str | None] = mapped_column(Text, nullable=True)

    project: Mapped[Project] = relationship(back_populates="approvals")
    run: Mapped[Run | None] = relationship(back_populates="approvals")

    def __repr__(self) -> str:
        return f"<Approval id={self.id} type={self.type!r} status={self.status!r}>"


# ── ToolCalls ─────────────────────────────────────────────────────────────────

class ToolCall(Base):
    __tablename__ = "tool_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    input_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run: Mapped[Run] = relationship(back_populates="tool_calls")

    def __repr__(self) -> str:
        return f"<ToolCall id={self.id} agent={self.agent_name!r} tool={self.tool_name!r}>"


# ── TraceLinks (Phase 2) ──────────────────────────────────────────────────────

class TraceLink(Base):
    """Maps a SoT requirement_id to a test_id for traceability.

    requirement_id: string ID from SoT requirements (e.g. "r1", "r2")
    test_id:        string identifier for the linked test case (e.g. "TC-001")
    link_type:      "test" | "backlog" | "architecture" (extensible)
    milestone_id:   optional MilestoneItem.id this link belongs to
    eval_type:      "unit" | "integration" | "e2e" | "contract" | "manual"
    source:         "manual" | "auto" — how the link was created
    """
    __tablename__ = "trace_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requirement_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    test_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    link_type: Mapped[str] = mapped_column(String(50), nullable=False, default="test")
    milestone_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    eval_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False, server_default="manual")
    last_run_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    project: Mapped["Project"] = relationship(back_populates="trace_links")

    def __repr__(self) -> str:
        return f"<TraceLink req={self.requirement_id!r} test={self.test_id!r}>"



# ── Phase 3: Multi-tenant governance models ───────────────────────────────────


class Organization(Base):
    """Tenant root — all resources are scoped to an org."""
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    # plan: "free" | "pro" | "enterprise"
    plan: Mapped[str] = mapped_column(String(50), nullable=False, default="free")
    settings_jsonb: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    users: Mapped[list["User"]] = relationship(
        back_populates="org", cascade="all, delete-orphan"
    )
    project_maps: Mapped[list["ProjectOrgMap"]] = relationship(
        back_populates="org", cascade="all, delete-orphan"
    )
    policies: Mapped[list["Policy"]] = relationship(
        back_populates="org", cascade="all, delete-orphan"
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="org")

    def __repr__(self) -> str:
        return f"<Organization id={self.id} slug={self.slug!r}>"


class User(Base):
    """Org member — can be assigned roles per org."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # role: "admin" | "pm" | "analyst" | "viewer"
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="viewer")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    org: Mapped[Organization] = relationship(back_populates="users")

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r} role={self.role!r}>"


class ProjectOrgMap(Base):
    """Many-to-many: Projects ↔ Organizations."""
    __tablename__ = "project_org_map"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    org_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    project: Mapped[Project] = relationship(back_populates="org_maps")
    org: Mapped[Organization] = relationship(back_populates="project_maps")

    def __repr__(self) -> str:
        return f"<ProjectOrgMap project_id={self.project_id} org_id={self.org_id}>"


class Policy(Base):
    """Governance policy — tool allowlists, budget caps, approval thresholds."""
    __tablename__ = "policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # policy_type: "tool_allowlist" | "budget" | "approval_threshold" | "composite"
    policy_type: Mapped[str] = mapped_column(String(100), nullable=False)
    # rules_jsonb: {"allowed_tools": [...], "max_cost_usd": 50.0, ...}
    rules_jsonb: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    org: Mapped[Organization] = relationship(back_populates="policies")

    def __repr__(self) -> str:
        return f"<Policy id={self.id} type={self.policy_type!r} org={self.org_id}>"


class BaselineSnapshot(Base):
    """A locked, labelled SoT snapshot — represents an approved project state."""
    __tablename__ = "baseline_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Soft ref to the live snapshots table row this was cloned from
    source_snapshot_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    state_jsonb: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    project: Mapped[Project] = relationship(back_populates="baseline_snapshots")
    change_requests: Mapped[list["ChangeRequest"]] = relationship(
        back_populates="baseline", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<BaselineSnapshot id={self.id} label={self.label!r} project={self.project_id}>"


class ChangeRequest(Base):
    """Tracks a proposed diff against a baseline for approval."""
    __tablename__ = "change_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    baseline_id: Mapped[int | None] = mapped_column(
        ForeignKey("baseline_snapshots.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # diff_jsonb: structured diff generated by diff.py
    diff_jsonb: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # status: "open" | "approved" | "rejected" | "withdrawn"
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="open")
    requested_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped[Project] = relationship(back_populates="change_requests")
    baseline: Mapped["BaselineSnapshot | None"] = relationship(back_populates="change_requests")

    def __repr__(self) -> str:
        return f"<ChangeRequest id={self.id} status={self.status!r} project={self.project_id}>"


class ProvenanceLink(Base):
    """Links an artifact section back to the SoT field + run node that produced it."""
    __tablename__ = "provenance_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    artifact_id: Mapped[int] = mapped_column(
        ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # sot_field: dot-notation path in ProjectState, e.g. "requirements.0.text"
    sot_field: Mapped[str] = mapped_column(String(255), nullable=False)
    # source_node: graph node that wrote this field, e.g. "prd"
    source_node: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    artifact: Mapped[Artifact] = relationship(back_populates="provenance_links")
    run: Mapped[Run] = relationship(back_populates="provenance_links")

    def __repr__(self) -> str:
        return f"<ProvenanceLink artifact={self.artifact_id} field={self.sot_field!r}>"


class AuditLog(Base):
    """Immutable event log — captures every material system action."""
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # actor: user email or "system"
    actor: Mapped[str] = mapped_column(String(255), nullable=False, default="system")
    # event_type: "run.started" | "approval.resolved" | "policy.blocked" | "baseline.created" ...
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    detail_jsonb: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    org: Mapped["Organization | None"] = relationship(back_populates="audit_logs")
    project: Mapped["Project | None"] = relationship(back_populates="audit_logs")
    run: Mapped["Run | None"] = relationship(back_populates="audit_logs")

    def __repr__(self) -> str:
        return f"<AuditLog id={self.id} event={self.event_type!r} actor={self.actor!r}>"


class ArtifactComment(Base):
    """Section-level review comments on a generated artifact."""
    __tablename__ = "artifact_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    artifact_id: Mapped[int] = mapped_column(
        ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # section: markdown heading or section ID (e.g. "## Problem Statement")
    section: Mapped[str | None] = mapped_column(String(255), nullable=True)
    author: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    artifact: Mapped[Artifact] = relationship(back_populates="comments")

    def __repr__(self) -> str:
        return f"<ArtifactComment id={self.id} artifact={self.artifact_id} resolved={self.resolved}>"


class ArtifactLintReport(Base):
    """Quality-gate findings from the linting engine on an artifact."""
    __tablename__ = "artifact_lint_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    artifact_id: Mapped[int] = mapped_column(
        ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # findings_jsonb: list of {rule, message, severity, section}
    findings_jsonb: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # severity_counts_jsonb: {"error": 0, "warning": 2, "info": 5}
    severity_counts_jsonb: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    artifact: Mapped[Artifact] = relationship(back_populates="lint_reports")

    def __repr__(self) -> str:
        return f"<ArtifactLintReport id={self.id} artifact={self.artifact_id} passed={self.passed}>"


class ComponentStore(Base):
    """Cross-project knowledge store — reusable patterns, templates, and decisions.

    Populated automatically when a project completes (end_node auto-extracts
    requirements, decisions, risks, and assumptions).  Retrieved at intake to
    pre-populate agent prompts with relevant institutional knowledge.

    component_type: "requirement_pattern" | "architecture_decision" |
                    "risk_pattern" | "assumption" | "sow_template" | "prd_section"
    category:       free-form domain tag, e.g. "auth", "payments", "saas"
    tags_json:      list[str] — keyword tags used for similarity retrieval
    content:        full text / JSON representation of the pattern
    source:         "auto" (extracted by end_node) | "manual" (via API)
    usage_count:    incremented each time this component is retrieved
    """
    __tablename__ = "component_store"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    component_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(100), nullable=False, default="general", index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tags_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="auto")
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<ComponentStore id={self.id} type={self.component_type!r} name={self.name!r}>"


class RunMetrics(Base):
    """Aggregated cost, token, and latency counters for a completed run."""
    __tablename__ = "run_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # node_metrics_jsonb: {"intake": {"tokens": 100, "latency_ms": 200}, ...}
    node_metrics_jsonb: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run: Mapped[Run] = relationship(back_populates="metrics")

    def __repr__(self) -> str:
        return (
            f"<RunMetrics id={self.id} run={self.run_id} "
            f"tokens={self.total_tokens} cost=${self.total_cost_usd:.4f}>"
        )
