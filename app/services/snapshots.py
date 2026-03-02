"""Snapshot service — Phase 1C.

Bridges the SoT (ProjectState) and the DB (snapshots table).

Public API:
  save_snapshot(db, run_id, state, step_id=None) -> Snapshot
  load_snapshot(db, snapshot_id) -> ProjectState
  load_latest_snapshot(db, run_id) -> ProjectState | None
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import Snapshot
from app.sot.state import ProjectState


def save_snapshot(
    db: Session,
    run_id: int,
    state: ProjectState,
    step_id: int | None = None,
) -> Snapshot:
    """Serialize *state* to JSONB and persist as a new Snapshot row.

    Args:
        db:      Active DB session.
        run_id:  The run this snapshot belongs to.
        state:   Current ProjectState to persist.
        step_id: Optional soft reference to the RunStep that triggered this save.

    Returns:
        The newly created Snapshot ORM object (already committed).
    """
    snapshot = Snapshot(
        run_id=run_id,
        step_id=step_id,
        state_jsonb=state.model_dump_jsonb(),
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def load_snapshot(db: Session, snapshot_id: int) -> ProjectState:
    """Deserialize a Snapshot row back into a ProjectState.

    Args:
        db:           Active DB session.
        snapshot_id:  Primary key of the Snapshot to load.

    Returns:
        Reconstructed ProjectState.

    Raises:
        ValueError: If the snapshot does not exist.
    """
    snapshot = db.get(Snapshot, snapshot_id)
    if snapshot is None:
        raise ValueError(f"Snapshot {snapshot_id} not found")
    return ProjectState(**snapshot.state_jsonb)


def load_latest_snapshot(db: Session, run_id: int) -> ProjectState | None:
    """Load the most recent Snapshot for a given run.

    Args:
        db:      Active DB session.
        run_id:  Run to query.

    Returns:
        Reconstructed ProjectState, or None if no snapshots exist yet.
    """
    snapshot = (
        db.query(Snapshot)
        .filter(Snapshot.run_id == run_id)
        .order_by(Snapshot.id.desc())
        .first()
    )
    if snapshot is None:
        return None
    return ProjectState(**snapshot.state_jsonb)
