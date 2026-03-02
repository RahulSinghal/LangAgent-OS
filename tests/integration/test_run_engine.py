"""Phase 1E integration tests — full run lifecycle against real PostgreSQL.

Tests the complete pause/resume cycle:
  1. start_run → pauses at discovery (waiting_user)
  2. resume_run (user answer) → pauses at prd_gate (waiting_approval)
  3. resume_run (prd approved) → pauses at sow_gate (waiting_approval)
  4. resume_run (sow approved) → completes
"""

import pytest
from sqlalchemy.orm import Session

from app.services.projects import create_project
from app.services.runs import get_run, start_run, resume_run
from app.sot.state import ApprovalStatus, Phase


def test_start_run_pauses_at_discovery(db: Session):
    project = create_project(db, name="Run Engine Project 1")

    run = start_run(db, project_id=project.id, user_message="Build me a CRM")

    assert run.id is not None
    assert run.status == "waiting_user"
    assert run.current_node == "discovery"


def test_resume_run_with_answer_pauses_at_prd_gate(db: Session):
    project = create_project(db, name="Run Engine Project 2")
    run = start_run(db, project_id=project.id, user_message="Build me a CRM")

    # User answers the discovery question — enough requirements will accumulate
    run = resume_run(db, run.id, user_message="It needs order management and CRM features")

    assert run.status == "waiting_approval"
    assert run.current_node == "prd_gate"


def test_resume_run_after_prd_approval_pauses_at_sow_gate(db: Session):
    project = create_project(db, name="Run Engine Project 3")
    run = start_run(db, project_id=project.id, user_message="Build me a CRM")
    run = resume_run(db, run.id, user_message="Order management required")

    assert run.status == "waiting_approval"

    # Simulate PRD approval by passing it via approval_patch
    run = resume_run(db, run.id, approval_patch={"prd": "approved"})

    assert run.status == "waiting_approval"
    assert run.current_node == "sow_gate"


def test_resume_run_after_sow_approval_completes(db: Session):
    project = create_project(db, name="Run Engine Project 4")
    run = start_run(db, project_id=project.id, user_message="Build me a CRM")
    run = resume_run(db, run.id, user_message="Order management required")
    run = resume_run(db, run.id, approval_patch={"prd": "approved"})
    run = resume_run(db, run.id, approval_patch={"sow": "approved"})

    assert run.status == "completed"
    assert run.current_node == "end"


def test_get_run_returns_correct_status(db: Session):
    project = create_project(db, name="Get Run Status Project")
    run = start_run(db, project_id=project.id, user_message="Build me a platform")

    fetched = get_run(db, run.id)
    assert fetched is not None
    assert fetched.status == run.status
    assert fetched.current_node == run.current_node


def test_resume_nonexistent_run_raises(db: Session):
    with pytest.raises(ValueError, match="not found"):
        resume_run(db, run_id=999999)


def test_start_run_creates_snapshot(db: Session):
    """A snapshot must be persisted after start_run."""
    from app.services.snapshots import load_latest_snapshot

    project = create_project(db, name="Snapshot After Start Project")
    run = start_run(db, project_id=project.id, user_message="Hello")

    snapshot = load_latest_snapshot(db, run.id)
    assert snapshot is not None
    assert snapshot.project_id == project.id


def test_full_run_snapshot_reflects_final_phase(db: Session):
    """After full completion, the latest snapshot should show phase=completed."""
    from app.services.snapshots import load_latest_snapshot

    project = create_project(db, name="Full Run Snapshot Project")
    run = start_run(db, project_id=project.id, user_message="Enterprise CRM")
    run = resume_run(db, run.id, user_message="Needs full CRM suite")
    run = resume_run(db, run.id, approval_patch={"prd": "approved"})
    run = resume_run(db, run.id, approval_patch={"sow": "approved"})

    latest = load_latest_snapshot(db, run.id)
    assert latest is not None
    assert latest.current_phase == Phase.COMPLETED
