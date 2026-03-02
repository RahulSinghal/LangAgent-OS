"""Change control service — Phase 3D.

Manages baseline snapshots and change requests with structured diffs.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models import BaselineSnapshot, ChangeRequest
from app.sot.diff import diff_summary


# ── Baselines ─────────────────────────────────────────────────────────────────

def create_baseline(
    db: Session,
    project_id: int,
    run_id: int | None,
    state_jsonb: dict,
    label: str,
    created_by: str | None = None,
) -> BaselineSnapshot:
    """Lock a SoT snapshot as a named baseline."""
    baseline = BaselineSnapshot(
        project_id=project_id,
        run_id=run_id,
        state_jsonb=state_jsonb,
        label=label,
        created_by=created_by,
    )
    db.add(baseline)
    db.commit()
    db.refresh(baseline)
    return baseline


def get_baseline(db: Session, baseline_id: int) -> BaselineSnapshot | None:
    """Return a baseline by primary key, or None."""
    return db.query(BaselineSnapshot).filter(BaselineSnapshot.id == baseline_id).first()


def list_baselines(db: Session, project_id: int) -> list[BaselineSnapshot]:
    """Return all baselines for a project, ordered by creation time."""
    return (
        db.query(BaselineSnapshot)
        .filter(BaselineSnapshot.project_id == project_id)
        .order_by(BaselineSnapshot.created_at)
        .all()
    )


# ── Change requests ───────────────────────────────────────────────────────────

def create_change_request(
    db: Session,
    project_id: int,
    baseline_id: int | None,
    old_state: dict,
    new_state: dict,
    requested_by: str | None = None,
) -> ChangeRequest:
    """Create a change request by computing the diff between old and new states."""
    diff = diff_summary(old_state, new_state)

    cr = ChangeRequest(
        project_id=project_id,
        baseline_id=baseline_id,
        diff_jsonb=diff,
        status="open",
        requested_by=requested_by,
    )
    db.add(cr)
    db.commit()
    db.refresh(cr)
    return cr


def resolve_change_request(
    db: Session,
    cr_id: int,
    decision: str,
    reviewed_by: str | None = None,
    review_notes: str | None = None,
) -> ChangeRequest:
    """Resolve a change request with 'approved' or 'rejected'.

    Raises ValueError if the CR is not in 'open' status.
    """
    cr = db.query(ChangeRequest).filter(ChangeRequest.id == cr_id).first()
    if cr is None:
        from fastapi import HTTPException, status as http_status
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"ChangeRequest {cr_id} not found",
        )
    if cr.status != "open":
        raise ValueError("already resolved")

    cr.status = decision
    cr.reviewed_by = reviewed_by
    cr.review_notes = review_notes
    cr.resolved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(cr)
    return cr


def get_change_request(db: Session, cr_id: int) -> ChangeRequest | None:
    """Return a change request by primary key, or None."""
    return db.query(ChangeRequest).filter(ChangeRequest.id == cr_id).first()


def list_change_requests(
    db: Session,
    project_id: int,
    status: str | None = None,
) -> list[ChangeRequest]:
    """Return all change requests for a project, optionally filtered by status."""
    q = db.query(ChangeRequest).filter(ChangeRequest.project_id == project_id)
    if status is not None:
        q = q.filter(ChangeRequest.status == status)
    return q.order_by(ChangeRequest.created_at).all()
