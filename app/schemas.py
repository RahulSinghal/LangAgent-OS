"""Pydantic v2 request/response schemas for all Phase 1 endpoints."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


# ── Shared ────────────────────────────────────────────────────────────────────

class OrmBase(BaseModel):
    """Base with ORM mode enabled for all response schemas."""
    model_config = ConfigDict(from_attributes=True)


# ── Projects ──────────────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Project name must not be empty")
        return v.strip()


class ProjectResponse(OrmBase):
    id: int
    name: str
    created_at: datetime


class ProjectList(BaseModel):
    projects: list[ProjectResponse]
    total: int


# ── Dashboard ─────────────────────────────────────────────────────────────────

class ArtifactSummary(BaseModel):
    id: int
    type: str
    version: int
    created_at: datetime


class ProjectDashboardRow(BaseModel):
    project_id: int
    name: str
    created_at: datetime
    latest_run_id: int | None = None
    current_state: str | None = None
    run_status: str | None = None
    pending_approvals: int = 0
    artifacts: dict[str, ArtifactSummary] = {}
    tokens_spent: int = 0
    cost_usd: float = 0.0
    system_runtime_ms: int = 0
    system_hours: float = 0.0
    last_activity_at: datetime | None = None


class ProjectDashboardList(BaseModel):
    projects: list[ProjectDashboardRow]
    total: int


# ── Workflow state graph ──────────────────────────────────────────────────────

class ProjectStateGraphPhase(BaseModel):
    id: str
    label: str
    status: str  # passed | current | pending


class ProjectStateGraphResponse(BaseModel):
    # Expose `id` to satisfy OpenAPI contract tests that expect all
    # Project*Response schemas to have an `id` field.
    id: int
    phases: list[ProjectStateGraphPhase]
    details: dict


# ── Sessions ──────────────────────────────────────────────────────────────────

class SessionCreate(BaseModel):
    channel: str = "api"


class SessionResponse(OrmBase):
    id: int
    project_id: int
    channel: str
    created_at: datetime


# ── Messages ──────────────────────────────────────────────────────────────────

class MessageCreate(BaseModel):
    role: str = "user"
    content: str

    @field_validator("role")
    @classmethod
    def valid_role(cls, v: str) -> str:
        if v not in ("user", "assistant", "system"):
            raise ValueError("role must be 'user', 'assistant', or 'system'")
        return v

    @field_validator("content")
    @classmethod
    def content_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Message content must not be empty")
        return v


class MessageResponse(OrmBase):
    id: int
    session_id: int
    role: str
    content: str
    created_at: datetime


class MessageList(BaseModel):
    messages: list[MessageResponse]


# ── Runs ──────────────────────────────────────────────────────────────────────

class RunStartRequest(BaseModel):
    project_id: int
    session_id: int | None = None
    user_message: str | None = None
    document_content: str | None = None   # raw text from an uploaded document
    document_filename: str | None = None  # original filename (used in summary)


class RunResumeRequest(BaseModel):
    user_message: str | None = None


class RunResponse(OrmBase):
    id: int
    project_id: int
    session_id: int | None
    status: str
    current_node: str | None
    created_at: datetime
    updated_at: datetime


# ── Approvals ─────────────────────────────────────────────────────────────────

class ApprovalResolveRequest(BaseModel):
    decision: str  # "approved" | "rejected"
    resolved_by: str | None = None
    comments: str | None = None

    @field_validator("decision")
    @classmethod
    def valid_decision(cls, v: str) -> str:
        if v not in ("approved", "rejected"):
            raise ValueError("decision must be 'approved' or 'rejected'")
        return v


class ApprovalResponse(OrmBase):
    id: int
    project_id: int
    run_id: int | None
    type: str
    status: str
    requested_at: datetime
    resolved_at: datetime | None
    requested_by: str | None
    resolved_by: str | None
    comments: str | None


# ── Artifacts ─────────────────────────────────────────────────────────────────

class ArtifactResponse(OrmBase):
    id: int
    project_id: int
    type: str
    version: int
    file_path: str | None
    created_at: datetime
    derived_from_snapshot_id: int | None


class ArtifactList(BaseModel):
    artifacts: list[ArtifactResponse]
