"""Integration tests for baselines and change requests — Phase 3D.

Tests: create_baseline, list_baselines, get_baseline,
       create_change_request, resolve_change_request,
       list_change_requests.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.services.projects import create_project
from app.services.change_control import (
    create_baseline,
    create_change_request,
    get_baseline,
    get_change_request,
    list_baselines,
    list_change_requests,
    resolve_change_request,
)


# ── Baseline CRUD ─────────────────────────────────────────────────────────────

_STATE_V1 = {
    "project_title": "AgentOS Platform",
    "current_phase": "prd",
    "requirements": [{"id": "r1", "text": "User login"}],
}

_STATE_V2 = {
    "project_title": "AgentOS Platform v2",
    "current_phase": "prd",
    "requirements": [
        {"id": "r1", "text": "User login"},
        {"id": "r2", "text": "Dashboard"},
    ],
}


def test_create_baseline_basic(db: Session):
    project = create_project(db, name="BaselineTest Project")
    baseline = create_baseline(
        db, project_id=project.id, run_id=None,
        state_jsonb=_STATE_V1, label="v1.0",
    )
    assert baseline.id is not None
    assert baseline.label == "v1.0"
    assert baseline.project_id == project.id
    assert baseline.state_jsonb == _STATE_V1


def test_create_baseline_with_run_id(db: Session):
    from app.services.runs import create_run
    project = create_project(db, name="BaselineRunTest")
    run = create_run(db, project_id=project.id)
    baseline = create_baseline(
        db, project_id=project.id, run_id=run.id,
        state_jsonb=_STATE_V1, label="after-run-1",
    )
    assert baseline.run_id == run.id


def test_create_baseline_with_creator(db: Session):
    project = create_project(db, name="CreatorBaseline")
    baseline = create_baseline(
        db, project_id=project.id, run_id=None,
        state_jsonb=_STATE_V1, label="PM Baseline",
        created_by="pm@company.com",
    )
    assert baseline.created_by == "pm@company.com"


def test_get_baseline_found(db: Session):
    project = create_project(db, name="GetBaseline Project")
    baseline = create_baseline(db, project_id=project.id, run_id=None, state_jsonb={}, label="lb")
    fetched = get_baseline(db, baseline.id)
    assert fetched is not None
    assert fetched.id == baseline.id


def test_get_baseline_not_found(db: Session):
    result = get_baseline(db, baseline_id=999999)
    assert result is None


def test_list_baselines_by_project(db: Session):
    project = create_project(db, name="ListBaselines Project")
    create_baseline(db, project_id=project.id, run_id=None, state_jsonb={}, label="B1")
    create_baseline(db, project_id=project.id, run_id=None, state_jsonb={}, label="B2")
    create_baseline(db, project_id=project.id, run_id=None, state_jsonb={}, label="B3")
    baselines = list_baselines(db, project_id=project.id)
    labels = [b.label for b in baselines]
    assert "B1" in labels
    assert "B2" in labels
    assert "B3" in labels


def test_list_baselines_isolated_by_project(db: Session):
    p1 = create_project(db, name="BLIso Project1")
    p2 = create_project(db, name="BLIso Project2")
    create_baseline(db, project_id=p1.id, run_id=None, state_jsonb={}, label="P1Baseline")
    create_baseline(db, project_id=p2.id, run_id=None, state_jsonb={}, label="P2Baseline")
    p1_baselines = list_baselines(db, project_id=p1.id)
    labels = [b.label for b in p1_baselines]
    assert "P1Baseline" in labels
    assert "P2Baseline" not in labels


# ── Change requests ───────────────────────────────────────────────────────────

def test_create_change_request_computes_diff(db: Session):
    project = create_project(db, name="CRDiff Project")
    cr = create_change_request(
        db, project_id=project.id,
        baseline_id=None,
        old_state=_STATE_V1,
        new_state=_STATE_V2,
        requested_by="developer@company.com",
    )
    assert cr.id is not None
    assert cr.status == "open"
    assert cr.requested_by == "developer@company.com"
    assert "total_changes" in cr.diff_jsonb
    assert cr.diff_jsonb["total_changes"] > 0


def test_create_change_request_no_diff_zero_changes(db: Session):
    project = create_project(db, name="CRNoDiff Project")
    cr = create_change_request(
        db, project_id=project.id,
        baseline_id=None,
        old_state=_STATE_V1,
        new_state=_STATE_V1,
    )
    assert cr.diff_jsonb["total_changes"] == 0


def test_create_change_request_with_baseline(db: Session):
    project = create_project(db, name="CRBaseline Project")
    baseline = create_baseline(db, project_id=project.id, run_id=None, state_jsonb=_STATE_V1, label="base")
    cr = create_change_request(
        db, project_id=project.id,
        baseline_id=baseline.id,
        old_state=_STATE_V1,
        new_state=_STATE_V2,
    )
    assert cr.baseline_id == baseline.id


def test_resolve_change_request_approved(db: Session):
    project = create_project(db, name="CRApprove Project")
    cr = create_change_request(db, project_id=project.id, baseline_id=None,
                               old_state={}, new_state={"key": "val"})
    resolved = resolve_change_request(
        db, cr_id=cr.id, decision="approved",
        reviewed_by="pm@company.com", review_notes="LGTM",
    )
    assert resolved.status == "approved"
    assert resolved.reviewed_by == "pm@company.com"
    assert resolved.review_notes == "LGTM"
    assert resolved.resolved_at is not None


def test_resolve_change_request_rejected(db: Session):
    project = create_project(db, name="CRReject Project")
    cr = create_change_request(db, project_id=project.id, baseline_id=None,
                               old_state={}, new_state={"x": 1})
    resolved = resolve_change_request(db, cr_id=cr.id, decision="rejected")
    assert resolved.status == "rejected"


def test_resolve_already_resolved_raises(db: Session):
    project = create_project(db, name="CRDoubleResolve Project")
    cr = create_change_request(db, project_id=project.id, baseline_id=None,
                               old_state={}, new_state={"x": 1})
    resolve_change_request(db, cr_id=cr.id, decision="approved")
    with pytest.raises(ValueError, match="already resolved"):
        resolve_change_request(db, cr_id=cr.id, decision="rejected")


def test_get_change_request(db: Session):
    project = create_project(db, name="CRGet Project")
    cr = create_change_request(db, project_id=project.id, baseline_id=None,
                               old_state={}, new_state={"a": 1})
    fetched = get_change_request(db, cr.id)
    assert fetched is not None
    assert fetched.id == cr.id


def test_get_change_request_not_found(db: Session):
    result = get_change_request(db, cr_id=999999)
    assert result is None


def test_list_change_requests_by_project(db: Session):
    project = create_project(db, name="ListCR Project")
    cr1 = create_change_request(db, project_id=project.id, baseline_id=None,
                                old_state={}, new_state={"a": 1})
    cr2 = create_change_request(db, project_id=project.id, baseline_id=None,
                                old_state={}, new_state={"b": 2})
    crs = list_change_requests(db, project_id=project.id)
    ids = [cr.id for cr in crs]
    assert cr1.id in ids
    assert cr2.id in ids


def test_list_change_requests_filter_by_status(db: Session):
    project = create_project(db, name="FilterCR Project")
    cr_open = create_change_request(db, project_id=project.id, baseline_id=None,
                                    old_state={}, new_state={"o": 1})
    cr_approved = create_change_request(db, project_id=project.id, baseline_id=None,
                                        old_state={}, new_state={"a": 1})
    resolve_change_request(db, cr_id=cr_approved.id, decision="approved")

    open_crs = list_change_requests(db, project_id=project.id, status="open")
    approved_crs = list_change_requests(db, project_id=project.id, status="approved")

    assert cr_open.id in [c.id for c in open_crs]
    assert cr_approved.id in [c.id for c in approved_crs]
    assert cr_approved.id not in [c.id for c in open_crs]


def test_diff_jsonb_fields_structure(db: Session):
    project = create_project(db, name="DiffStructure Project")
    cr = create_change_request(
        db, project_id=project.id, baseline_id=None,
        old_state={"title": "Old"}, new_state={"title": "New", "extra": "field"},
    )
    diff = cr.diff_jsonb
    assert "changes" in diff
    assert "added_fields" in diff
    assert "removed_fields" in diff
    assert "changed_fields" in diff
    assert "total_changes" in diff
    assert "title" in diff["changed_fields"]
    assert "extra" in diff["added_fields"]
