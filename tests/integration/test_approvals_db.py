"""Phase 1F integration tests — artifact generation + approval resolution.

Tests the complete flow:
  start_run → waiting_user
  resume_run (answer) → waiting_approval → artifact file created, Approval record created
  GET /runs/{id}/approval → returns pending approval id
  resolve_approval (approved) → run resumes → next gate or completed
"""

import pytest
from pathlib import Path
from sqlalchemy.orm import Session

from app.services.projects import create_project
from app.services.runs import start_run, resume_run
from app.services.approvals import (
    create_approval,
    get_approval,
    get_pending_approval_for_run,
    resolve_approval,
)
from app.services.artifacts import list_artifacts, read_artifact_content
from app.sot.state import Phase


# ── Approval CRUD ──────────────────────────────────────────────────────────────

def test_create_and_get_approval(db: Session):
    project = create_project(db, name="Approval CRUD Project")
    from app.services.runs import create_run
    run = create_run(db, project_id=project.id)

    approval = create_approval(db, project_id=project.id, run_id=run.id, artifact_type="prd")
    assert approval.id is not None
    assert approval.status == "pending"
    assert approval.type == "prd"

    fetched = get_approval(db, approval.id)
    assert fetched is not None
    assert fetched.id == approval.id


def test_resolve_approval_without_run(db: Session):
    """resolve_approval on an approval with no linked run just updates the record."""
    project = create_project(db, name="Standalone Approval Project")
    approval = create_approval(db, project_id=project.id, run_id=None, artifact_type="prd")

    resolved = resolve_approval(
        db,
        approval_id=approval.id,
        decision="approved",
        resolved_by="alice@example.com",
        comments="Looks good",
    )
    assert resolved.status == "approved"
    assert resolved.resolved_by == "alice@example.com"
    assert resolved.comments == "Looks good"
    assert resolved.resolved_at is not None


def test_resolve_already_resolved_raises(db: Session):
    project = create_project(db, name="Double Resolve Project")
    approval = create_approval(db, project_id=project.id, run_id=None, artifact_type="sow")
    resolve_approval(db, approval.id, decision="approved")

    with pytest.raises(ValueError, match="already resolved"):
        resolve_approval(db, approval.id, decision="rejected")


def test_resolve_nonexistent_approval_raises(db: Session):
    with pytest.raises(ValueError, match="not found"):
        resolve_approval(db, approval_id=999999, decision="approved")


# ── Full flow: artifact created on run pause ──────────────────────────────────

def test_artifact_created_when_run_pauses_at_prd_gate(db: Session, tmp_path):
    """After a run reaches the PRD approval gate, an artifact file must exist."""
    import app.artifacts.generator as gen_module
    original_dir = gen_module.settings.ARTIFACTS_DIR

    try:
        # Redirect artifact storage to tmp_path for test isolation
        gen_module.settings.__class__.ARTIFACTS_DIR = property(lambda self: str(tmp_path))

        project = create_project(db, name="Artifact Flow Project")
        run = start_run(db, project_id=project.id, user_message="Build me a platform")
        run = resume_run(db, run.id, user_message="Needs reporting and analytics")

        assert run.status == "waiting_approval"

        # Artifact record should exist
        artifacts = list_artifacts(db, project.id)
        assert len(artifacts) >= 1
        prd_artifact = next((a for a in artifacts if a.type == "prd"), None)
        assert prd_artifact is not None
        assert prd_artifact.file_path is not None
        assert Path(prd_artifact.file_path).exists()

    finally:
        # Restore (best effort)
        pass


def test_approval_record_created_on_run_pause(db: Session):
    """An Approval record is created when a run pauses at a gate."""
    project = create_project(db, name="Approval Record Flow Project")
    run = start_run(db, project_id=project.id, user_message="Build a CRM")
    run = resume_run(db, run.id, user_message="Order management required")

    assert run.status == "waiting_approval"

    # Pending approval should exist
    approval = get_pending_approval_for_run(db, run.id)
    assert approval is not None
    assert approval.type == "prd"
    assert approval.status == "pending"
    assert approval.run_id == run.id


def test_get_pending_approval_returns_none_if_no_approval(db: Session):
    project = create_project(db, name="No Approval Project")
    from app.services.runs import create_run
    run = create_run(db, project_id=project.id)

    result = get_pending_approval_for_run(db, run.id)
    assert result is None


def test_full_flow_with_approval_resolution(db: Session):
    """End-to-end: start → discovery → prd_gate → resolve → sow_gate → resolve → complete."""
    project = create_project(db, name="E2E Approval Flow Project")

    # Step 1: start
    run = start_run(db, project_id=project.id, user_message="Enterprise analytics platform")
    assert run.status == "waiting_user"

    # Step 2: user answers discovery question
    run = resume_run(db, run.id, user_message="Real-time dashboards and data pipelines")
    assert run.status == "waiting_approval"
    assert run.current_node == "prd_gate"

    # Step 3: resolve PRD approval
    prd_approval = get_pending_approval_for_run(db, run.id)
    assert prd_approval is not None
    resolve_approval(
        db,
        approval_id=prd_approval.id,
        decision="approved",
        resolved_by="product.manager@company.com",
    )

    # After resolve, run should have moved to SOW gate
    from app.services.runs import get_run
    run = get_run(db, run.id)
    assert run.status == "waiting_approval"
    assert run.current_node == "sow_gate"

    # Step 4: resolve SOW approval
    sow_approval = get_pending_approval_for_run(db, run.id)
    assert sow_approval is not None
    assert sow_approval.type == "sow"

    resolve_approval(
        db,
        approval_id=sow_approval.id,
        decision="approved",
        resolved_by="engagement.manager@company.com",
        comments="SOW approved for signature",
    )

    # Final state: completed
    run = get_run(db, run.id)
    assert run.status == "completed"
    assert run.current_node == "end"

    # Verify snapshot phase
    from app.services.snapshots import load_latest_snapshot
    final_sot = load_latest_snapshot(db, run.id)
    assert final_sot.current_phase == Phase.COMPLETED

    # Verify artifacts exist for both prd and sow
    artifacts = list_artifacts(db, project.id)
    artifact_types = {a.type for a in artifacts}
    assert "prd" in artifact_types
    assert "sow" in artifact_types
