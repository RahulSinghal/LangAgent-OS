"""Governance routes -- Phase 3 (3D-3G).

Covers baselines, change requests, comments, lint,provenance, metrics, audit log and ZIP export.
"""
from __future__ import annotations
import io
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.services.change_control import (
    create_baseline, create_change_request, get_baseline,
    list_baselines, list_change_requests, resolve_change_request,
)
from app.services.comments import add_comment, list_comments, resolve_comment
from app.services.export_service import build_export_zip
from app.services.linting import get_lint_report, lint_artifact, save_lint_report
from app.services.provenance import get_audit_log, get_provenance, get_run_metrics
router = APIRouter(tags=["governance"])
DbDep = Annotated[Session, Depends(get_db)]


class CreateBaselineRequest(BaseModel):
    run_id: int | None = None
    state_jsonb: dict
    label: str
    created_by: str | None = None


class BaselineResponse(BaseModel):
    id: int
    project_id: int
    run_id: int | None
    label: str
    state_jsonb: dict
    created_by: str | None
    created_at: str
    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_obj(cls, obj):
        return cls(id=obj.id, project_id=obj.project_id, run_id=obj.run_id, label=obj.label,
            state_jsonb=obj.state_jsonb, created_by=obj.created_by, created_at=obj.created_at.isoformat())


class CreateCRRequest(BaseModel):
    baseline_id: int | None = None
    old_state: dict
    new_state: dict
    requested_by: str | None = None


class ResolveCRRequest(BaseModel):
    decision: str
    reviewed_by: str | None = None
    review_notes: str | None = None


class CRResponse(BaseModel):
    id: int
    project_id: int
    baseline_id: int | None
    diff_jsonb: dict
    status: str
    requested_by: str | None
    reviewed_by: str | None
    review_notes: str | None
    created_at: str
    resolved_at: str | None

    @classmethod
    def from_orm_obj(cls, obj):
        return cls(id=obj.id, project_id=obj.project_id, baseline_id=obj.baseline_id,
            diff_jsonb=obj.diff_jsonb, status=obj.status, requested_by=obj.requested_by,
            reviewed_by=obj.reviewed_by, review_notes=obj.review_notes,
            created_at=obj.created_at.isoformat(),
            resolved_at=obj.resolved_at.isoformat() if obj.resolved_at else None)


class AddCommentRequest(BaseModel):
    project_id: int
    author: str
    body: str
    section: str | None = None


class CommentResponse(BaseModel):
    id: int
    artifact_id: int
    project_id: int
    author: str
    body: str
    section: str | None
    resolved: bool
    created_at: str

    @classmethod
    def from_orm_obj(cls, obj):
        return cls(id=obj.id, artifact_id=obj.artifact_id, project_id=obj.project_id,
            author=obj.author, body=obj.body, section=obj.section, resolved=obj.resolved,
            created_at=obj.created_at.isoformat())


class LintRequest(BaseModel):
    artifact_type: str
    content: str
    run_id: int | None = None


class LintResponse(BaseModel):
    id: int
    artifact_id: int
    run_id: int | None
    findings_jsonb: list
    severity_counts_jsonb: dict
    passed: bool
    created_at: str

    @classmethod
    def from_orm_obj(cls, obj):
        return cls(id=obj.id, artifact_id=obj.artifact_id, run_id=obj.run_id,
            findings_jsonb=obj.findings_jsonb, severity_counts_jsonb=obj.severity_counts_jsonb,
            passed=obj.passed, created_at=obj.created_at.isoformat())


class ProvenanceResponse(BaseModel):
    id: int
    artifact_id: int
    run_id: int
    sot_field: str
    source_node: str
    created_at: str

    @classmethod
    def from_orm_obj(cls, obj):
        return cls(id=obj.id, artifact_id=obj.artifact_id, run_id=obj.run_id,
            sot_field=obj.sot_field, source_node=obj.source_node, created_at=obj.created_at.isoformat())


class MetricsResponse(BaseModel):
    id: int
    run_id: int
    project_id: int
    total_tokens: int
    total_cost_usd: float
    total_latency_ms: int
    node_metrics_jsonb: dict
    created_at: str

    @classmethod
    def from_orm_obj(cls, obj):
        return cls(id=obj.id, run_id=obj.run_id, project_id=obj.project_id,
            total_tokens=obj.total_tokens, total_cost_usd=obj.total_cost_usd,
            total_latency_ms=obj.total_latency_ms, node_metrics_jsonb=obj.node_metrics_jsonb,
            created_at=obj.created_at.isoformat())


class AuditLogResponse(BaseModel):
    id: int
    org_id: int | None
    project_id: int | None
    run_id: int | None
    actor: str
    event_type: str
    detail_jsonb: dict
    created_at: str

    @classmethod
    def from_orm_obj(cls, obj):
        return cls(id=obj.id, org_id=obj.org_id, project_id=obj.project_id, run_id=obj.run_id,
            actor=obj.actor, event_type=obj.event_type, detail_jsonb=obj.detail_jsonb,
            created_at=obj.created_at.isoformat())


# ---- Baseline routes ----

@router.post(
    "/projects/{project_id}/baselines",
    response_model=BaselineResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_baseline_route(project_id: int, body: CreateBaselineRequest, db: DbDep) -> BaselineResponse:
    baseline = create_baseline(db, project_id=project_id, run_id=body.run_id,
        state_jsonb=body.state_jsonb, label=body.label, created_by=body.created_by)
    return BaselineResponse.from_orm_obj(baseline)


@router.get("/projects/{project_id}/baselines", response_model=list[BaselineResponse])
def list_baselines_route(project_id: int, db: DbDep) -> list[BaselineResponse]:
    return [BaselineResponse.from_orm_obj(b) for b in list_baselines(db, project_id=project_id)]


@router.get("/baselines/{baseline_id}", response_model=BaselineResponse)
def get_baseline_route(baseline_id: int, db: DbDep) -> BaselineResponse:
    baseline = get_baseline(db, baseline_id)
    if baseline is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Baseline {baseline_id} not found")
    return BaselineResponse.from_orm_obj(baseline)


# ---- Change request routes ----

@router.post(
    "/projects/{project_id}/change-requests",
    response_model=CRResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_cr_route(project_id: int, body: CreateCRRequest, db: DbDep) -> CRResponse:
    cr = create_change_request(db, project_id=project_id, baseline_id=body.baseline_id,
        old_state=body.old_state, new_state=body.new_state, requested_by=body.requested_by)
    return CRResponse.from_orm_obj(cr)


@router.get("/projects/{project_id}/change-requests", response_model=list[CRResponse])
def list_crs_route(project_id: int, db: DbDep, cr_status: str | None = None) -> list[CRResponse]:
    return [CRResponse.from_orm_obj(cr) for cr in list_change_requests(db, project_id=project_id, status=cr_status)]


@router.post("/change-requests/{cr_id}/resolve", response_model=CRResponse)
def resolve_cr_route(cr_id: int, body: ResolveCRRequest, db: DbDep) -> CRResponse:
    try:
        cr = resolve_change_request(db, cr_id=cr_id, decision=body.decision,
            reviewed_by=body.reviewed_by, review_notes=body.review_notes)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return CRResponse.from_orm_obj(cr)


# ---- Comment routes ----

@router.post(
    "/artifacts/{artifact_id}/comments",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_comment_route(artifact_id: int, body: AddCommentRequest, db: DbDep) -> CommentResponse:
    comment = add_comment(db, artifact_id=artifact_id, project_id=body.project_id,
        author=body.author, body=body.body, section=body.section)
    return CommentResponse.from_orm_obj(comment)


@router.get("/artifacts/{artifact_id}/comments", response_model=list[CommentResponse])
def list_comments_route(artifact_id: int, db: DbDep, include_resolved: bool = True) -> list[CommentResponse]:
    return [CommentResponse.from_orm_obj(c) for c in list_comments(db, artifact_id=artifact_id, include_resolved=include_resolved)]


@router.post(
    "/artifacts/{artifact_id}/comments/{comment_id}/resolve",
    response_model=CommentResponse,
)
def resolve_comment_route(artifact_id: int, comment_id: int, db: DbDep) -> CommentResponse:
    return CommentResponse.from_orm_obj(resolve_comment(db, comment_id=comment_id))


# ---- Lint routes ----

@router.post(
    "/artifacts/{artifact_id}/lint",
    response_model=LintResponse,
    status_code=status.HTTP_201_CREATED,
)
def run_lint_route(artifact_id: int, body: LintRequest, db: DbDep) -> LintResponse:
    report = lint_artifact(content=body.content, artifact_type=body.artifact_type)
    lint_report = save_lint_report(db, artifact_id=artifact_id, run_id=body.run_id, report=report)
    return LintResponse.from_orm_obj(lint_report)


@router.get("/artifacts/{artifact_id}/lint", response_model=LintResponse)
def get_lint_route(artifact_id: int, db: DbDep) -> LintResponse:
    report = get_lint_report(db, artifact_id=artifact_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No lint report found for artifact {artifact_id}")
    return LintResponse.from_orm_obj(report)


# ---- Provenance routes ----

@router.get("/artifacts/{artifact_id}/provenance", response_model=list[ProvenanceResponse])
def get_provenance_route(artifact_id: int, db: DbDep) -> list[ProvenanceResponse]:
    return [ProvenanceResponse.from_orm_obj(lnk) for lnk in get_provenance(db, artifact_id=artifact_id)]


# ---- Run metrics routes ----

@router.get("/runs/{run_id}/metrics", response_model=MetricsResponse)
def get_run_metrics_route(run_id: int, db: DbDep) -> MetricsResponse:
    metrics = get_run_metrics(db, run_id=run_id)
    if metrics is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No metrics found for run {run_id}")
    return MetricsResponse.from_orm_obj(metrics)


@router.get("/runs/{run_id}/trace", response_model=list[AuditLogResponse])
def get_run_trace_route(run_id: int, db: DbDep, limit: int = 100) -> list[AuditLogResponse]:
    return [AuditLogResponse.from_orm_obj(e) for e in get_audit_log(db, run_id=run_id, limit=limit)]


# ---- Audit log routes ----

@router.get("/projects/{project_id}/audit-log", response_model=list[AuditLogResponse])
def get_project_audit_log_route(project_id: int, db: DbDep, limit: int = 100) -> list[AuditLogResponse]:
    return [AuditLogResponse.from_orm_obj(e) for e in get_audit_log(db, project_id=project_id, limit=limit)]


# ---- Export route ----

@router.get("/projects/{project_id}/export")
def export_project_route(project_id: int, db: DbDep) -> StreamingResponse:
    try:
        zip_bytes = build_export_zip(db, project_id=project_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return StreamingResponse(
        content=io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=project_{project_id}_export.zip"},
    )

