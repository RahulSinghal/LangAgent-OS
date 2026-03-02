"""Integration tests for provenance, run metrics, and audit log — Phase 3F.

Tests: record_provenance, get_provenance, record_run_metrics, get_run_metrics,
       log_audit_event, get_audit_log.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.services.projects import create_project
from app.services.runs import create_run
from app.services.auth import create_org
from app.services.provenance import (
    get_audit_log,
    get_provenance,
    get_run_metrics,
    log_audit_event,
    record_provenance,
    record_run_metrics,
)


# ── Provenance links ──────────────────────────────────────────────────────────

def _make_artifact(db, project_id: int):
    """Create a minimal artifact record."""
    from app.db.models import Artifact
    art = Artifact(project_id=project_id, type="prd", version=1)
    db.add(art)
    db.commit()
    db.refresh(art)
    return art


def test_record_provenance_creates_links(db: Session):
    project = create_project(db, name="Provenance Project A")
    run = create_run(db, project_id=project.id)
    artifact = _make_artifact(db, project.id)

    links = record_provenance(
        db,
        artifact_id=artifact.id,
        run_id=run.id,
        sot_fields=["requirements.0.text", "goals.0", "problem_statement"],
        source_node="prd",
    )
    assert len(links) == 3
    fields = [lk.sot_field for lk in links]
    assert "requirements.0.text" in fields
    assert "goals.0" in fields
    assert "problem_statement" in fields


def test_record_provenance_sets_source_node(db: Session):
    project = create_project(db, name="Provenance Project B")
    run = create_run(db, project_id=project.id)
    artifact = _make_artifact(db, project.id)

    links = record_provenance(
        db, artifact_id=artifact.id, run_id=run.id,
        sot_fields=["scope.include"], source_node="sow",
    )
    assert links[0].source_node == "sow"


def test_record_provenance_empty_fields(db: Session):
    project = create_project(db, name="Provenance Project C")
    run = create_run(db, project_id=project.id)
    artifact = _make_artifact(db, project.id)
    links = record_provenance(db, artifact_id=artifact.id, run_id=run.id,
                              sot_fields=[], source_node="prd")
    assert links == []


def test_get_provenance_returns_links(db: Session):
    project = create_project(db, name="GetProvenance Project")
    run = create_run(db, project_id=project.id)
    artifact = _make_artifact(db, project.id)
    record_provenance(db, artifact_id=artifact.id, run_id=run.id,
                      sot_fields=["title", "scope"], source_node="prd")
    links = get_provenance(db, artifact_id=artifact.id)
    assert len(links) == 2


def test_get_provenance_no_links_returns_empty(db: Session):
    project = create_project(db, name="EmptyProvenance Project")
    artifact = _make_artifact(db, project.id)
    links = get_provenance(db, artifact_id=artifact.id)
    assert links == []


# ── Run metrics ───────────────────────────────────────────────────────────────

def test_record_run_metrics_basic(db: Session):
    project = create_project(db, name="Metrics Project A")
    run = create_run(db, project_id=project.id)
    metrics = record_run_metrics(
        db, run_id=run.id, project_id=project.id,
        total_tokens=1500, total_cost_usd=0.023, total_latency_ms=4200,
    )
    assert metrics.id is not None
    assert metrics.run_id == run.id
    assert metrics.total_tokens == 1500
    assert abs(metrics.total_cost_usd - 0.023) < 1e-6
    assert metrics.total_latency_ms == 4200


def test_record_run_metrics_with_node_breakdown(db: Session):
    project = create_project(db, name="Metrics Project B")
    run = create_run(db, project_id=project.id)
    node_data = {"intake": {"tokens": 200, "latency_ms": 800}}
    metrics = record_run_metrics(
        db, run_id=run.id, project_id=project.id,
        total_tokens=200, node_metrics=node_data,
    )
    assert metrics.node_metrics_jsonb == node_data


def test_record_run_metrics_upsert(db: Session):
    project = create_project(db, name="Metrics Upsert Project")
    run = create_run(db, project_id=project.id)
    # First write
    record_run_metrics(db, run_id=run.id, project_id=project.id, total_tokens=100)
    # Upsert
    metrics = record_run_metrics(db, run_id=run.id, project_id=project.id, total_tokens=999)
    assert metrics.total_tokens == 999
    # Should not create a second row
    all_metrics = db.query(__import__("app.db.models", fromlist=["RunMetrics"]).RunMetrics).filter_by(run_id=run.id).all()
    assert len(all_metrics) == 1


def test_get_run_metrics_found(db: Session):
    project = create_project(db, name="GetMetrics Project")
    run = create_run(db, project_id=project.id)
    record_run_metrics(db, run_id=run.id, project_id=project.id, total_tokens=500)
    fetched = get_run_metrics(db, run_id=run.id)
    assert fetched is not None
    assert fetched.total_tokens == 500


def test_get_run_metrics_not_found(db: Session):
    result = get_run_metrics(db, run_id=999999)
    assert result is None


# ── Audit log ─────────────────────────────────────────────────────────────────

def test_log_audit_event_basic(db: Session):
    entry = log_audit_event(db, event_type="run.started", actor="system")
    assert entry.id is not None
    assert entry.event_type == "run.started"
    assert entry.actor == "system"


def test_log_audit_event_with_project(db: Session):
    project = create_project(db, name="AuditLog Project A")
    entry = log_audit_event(
        db, event_type="approval.resolved",
        actor="pm@company.com",
        project_id=project.id,
        detail={"decision": "approved"},
    )
    assert entry.project_id == project.id
    assert entry.detail_jsonb["decision"] == "approved"


def test_log_audit_event_with_run(db: Session):
    project = create_project(db, name="AuditLog Project B")
    run = create_run(db, project_id=project.id)
    entry = log_audit_event(
        db, event_type="policy.blocked",
        run_id=run.id, detail={"tool": "exec_code"},
    )
    assert entry.run_id == run.id


def test_log_audit_event_with_org(db: Session):
    org = create_org(db, name="AuditLogOrg")
    entry = log_audit_event(db, event_type="org.created", org_id=org.id)
    assert entry.org_id == org.id


def test_get_audit_log_by_project(db: Session):
    project = create_project(db, name="GetAudit Project")
    log_audit_event(db, event_type="test.event1", project_id=project.id)
    log_audit_event(db, event_type="test.event2", project_id=project.id)
    logs = get_audit_log(db, project_id=project.id)
    types = [e.event_type for e in logs]
    assert "test.event1" in types
    assert "test.event2" in types


def test_get_audit_log_by_run(db: Session):
    project = create_project(db, name="GetAuditRun Project")
    run = create_run(db, project_id=project.id)
    log_audit_event(db, event_type="run.completed", run_id=run.id)
    logs = get_audit_log(db, run_id=run.id)
    assert any(e.event_type == "run.completed" for e in logs)


def test_get_audit_log_limit(db: Session):
    project = create_project(db, name="AuditLimit Project")
    for i in range(5):
        log_audit_event(db, event_type=f"event.{i}", project_id=project.id)
    logs = get_audit_log(db, project_id=project.id, limit=3)
    assert len(logs) <= 3


def test_audit_log_is_ordered_desc(db: Session):
    project = create_project(db, name="AuditOrder Project")
    log_audit_event(db, event_type="first.event", project_id=project.id)
    log_audit_event(db, event_type="second.event", project_id=project.id)
    logs = get_audit_log(db, project_id=project.id)
    # Most recent first
    assert logs[0].event_type == "second.event"
