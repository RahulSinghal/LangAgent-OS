"""Phase 1C integration tests — snapshot save/load against real PostgreSQL."""

import pytest
from sqlalchemy.orm import Session

from app.services.projects import create_project
from app.services.runs import create_run
from app.services.snapshots import load_latest_snapshot, load_snapshot, save_snapshot
from app.sot.patch import apply_patch
from app.sot.state import Phase, create_initial_state


def test_save_and_load_snapshot(db: Session):
    project = create_project(db, name="Snapshot Project")
    run = create_run(db, project_id=project.id)

    state = create_initial_state(project_id=project.id, run_id=run.id)
    snapshot = save_snapshot(db, run_id=run.id, state=state)

    assert snapshot.id is not None
    assert snapshot.run_id == run.id
    assert snapshot.step_id is None

    restored = load_snapshot(db, snapshot.id)
    assert restored.project_id == project.id
    assert restored.run_id == run.id
    assert restored.current_phase == Phase.INIT


def test_snapshot_preserves_patch(db: Session):
    """State with a patch applied survives serialise → DB → deserialise."""
    project = create_project(db, name="Patch Snapshot Project")
    run = create_run(db, project_id=project.id)

    state = create_initial_state(project_id=project.id, run_id=run.id)
    patched = apply_patch(
        state,
        {
            "current_phase": "discovery",
            "last_user_message": "Let's start",
            "requirements": [{"category": "functional", "text": "User login"}],
        },
    )
    snapshot = save_snapshot(db, run_id=run.id, state=patched)
    restored = load_snapshot(db, snapshot.id)

    assert restored.current_phase == Phase.DISCOVERY
    assert restored.last_user_message == "Let's start"
    assert len(restored.requirements) == 1
    assert restored.requirements[0].text == "User login"


def test_load_latest_snapshot(db: Session):
    """load_latest_snapshot returns the most recent snapshot for a run."""
    project = create_project(db, name="Latest Snapshot Project")
    run = create_run(db, project_id=project.id)

    state1 = create_initial_state(project_id=project.id, run_id=run.id)
    save_snapshot(db, run_id=run.id, state=state1)

    state2 = apply_patch(state1, {"current_phase": "prd"})
    save_snapshot(db, run_id=run.id, state=state2)

    latest = load_latest_snapshot(db, run_id=run.id)
    assert latest is not None
    assert latest.current_phase == Phase.PRD


def test_load_latest_snapshot_no_snapshots(db: Session):
    project = create_project(db, name="Empty Run Project")
    run = create_run(db, project_id=project.id)

    result = load_latest_snapshot(db, run_id=run.id)
    assert result is None


def test_load_snapshot_not_found_raises(db: Session):
    with pytest.raises(ValueError, match="not found"):
        load_snapshot(db, snapshot_id=999999)
