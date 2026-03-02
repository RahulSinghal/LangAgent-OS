"""Approval service — Phase 1F.

Creates and resolves Approval records.
On resolve: applies the decision to the SoT and resumes the run.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models import Approval


def create_approval(
    db: Session,
    project_id: int,
    run_id: int,
    artifact_type: str,
    requested_by: str | None = None,
) -> Approval:
    """Create a pending Approval record for an artifact gate."""
    approval = Approval(
        project_id=project_id,
        run_id=run_id,
        type=artifact_type,
        status="pending",
        requested_by=requested_by,
    )
    db.add(approval)
    db.commit()
    db.refresh(approval)
    return approval


def get_approval(db: Session, approval_id: int) -> Approval | None:
    return db.get(Approval, approval_id)


def get_pending_approval_for_run(db: Session, run_id: int) -> Approval | None:
    """Return the most recent pending Approval for a run, or None."""
    return (
        db.query(Approval)
        .filter(Approval.run_id == run_id, Approval.status == "pending")
        .order_by(Approval.requested_at.desc())
        .first()
    )


def list_pending_approvals_for_run(db: Session, run_id: int) -> list[Approval]:
    """Return all pending approvals for a run, newest first."""
    return (
        db.query(Approval)
        .filter(Approval.run_id == run_id, Approval.status == "pending")
        .order_by(Approval.requested_at.desc())
        .all()
    )


def ensure_pending_approval(
    db: Session,
    project_id: int,
    run_id: int,
    approval_type: str,
    requested_by: str | None = None,
) -> Approval:
    """Ensure a pending approval exists for (run_id, approval_type).

    Prevents duplicate pending approvals when a run is resumed into a gate.
    """
    existing = (
        db.query(Approval)
        .filter(
            Approval.run_id == run_id,
            Approval.type == approval_type,
            Approval.status == "pending",
        )
        .order_by(Approval.requested_at.desc())
        .first()
    )
    if existing is not None:
        return existing
    return create_approval(
        db,
        project_id=project_id,
        run_id=run_id,
        artifact_type=approval_type,
        requested_by=requested_by,
    )


def resolve_approval(
    db: Session,
    approval_id: int,
    decision: str,            # "approved" | "rejected"
    resolved_by: str | None = None,
    comments: str | None = None,
) -> Approval:
    """Resolve an approval and resume the associated run.

    Args:
        db:          Active DB session.
        approval_id: Approval to resolve.
        decision:    "approved" | "rejected"
        resolved_by: Name/email of the approver.
        comments:    Optional reviewer comments.

    Returns:
        Updated Approval record.

    Raises:
        ValueError: Approval not found or already resolved.
    """
    approval = db.get(Approval, approval_id)
    if approval is None:
        raise ValueError(f"Approval {approval_id} not found")
    if approval.status != "pending":
        raise ValueError(
            f"Approval {approval_id} is already resolved (status={approval.status!r})"
        )

    # Update approval record
    approval.status = decision
    approval.resolved_by = resolved_by
    approval.comments = comments
    approval.resolved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(approval)

    # Persist approval action into session conversation (if linked)
    try:
        if approval.run_id is not None:
            from app.db.models import Run
            run = db.get(Run, approval.run_id)
            if run and run.session_id:
                from app.services.sessions import add_message
                comment = (comments or "").strip()
                note = (
                    f"Approval resolved: type={approval.type}, decision={decision}."
                    + (f"\nComments: {comment}" if comment else "")
                )
                add_message(db, session_id=run.session_id, role="system", content=note)
    except Exception:
        pass

    # Resume the associated run with the approval decision
    if approval.run_id is not None:
        from app.services.runs import resume_run
        resume_run(
            db,
            run_id=approval.run_id,
            approval_patch={approval.type: decision},
        )

    return approval
