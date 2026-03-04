from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import Approval, Artifact, Run
from app.services.snapshots import load_latest_snapshot


_PHASES: list[str] = [
    "init",
    "discovery",
    "market_eval",
    "prd",
    "commercials",
    "sow",
    "coding",
    "milestone",
    "completed",
]


def _phase_statuses(current_phase: str) -> dict[str, str]:
    """Return mapping phase -> passed|current|pending based on ordering."""
    try:
        idx = _PHASES.index(current_phase)
    except ValueError:
        idx = 0
        current_phase = "init"
    out: dict[str, str] = {}
    for i, p in enumerate(_PHASES):
        if i < idx:
            out[p] = "passed"
        elif i == idx:
            out[p] = "current"
        else:
            out[p] = "pending"
    return out


def get_project_state_graph(db: Session, project_id: int) -> dict:
    """Compute a workflow state graph + substates for a given project.

    Uses the latest run's latest snapshot as the source of current_phase and details.
    Falls back gracefully when no run/snapshot exists.
    """
    latest_run: Run | None = (
        db.query(Run).filter(Run.project_id == project_id).order_by(Run.created_at.desc()).first()
    )

    sot = None
    if latest_run is not None:
        sot = load_latest_snapshot(db, latest_run.id)

    current_phase = "init"
    rejection_feedback = None
    unanswered_questions = 0
    approvals_status = {}
    hosting_preference = None

    if sot is not None:
        current_phase = getattr(getattr(sot, "current_phase", None), "value", None) or "init"
        rejection_feedback = getattr(sot, "rejection_feedback", None)
        hosting_preference = getattr(sot, "hosting_preference", None)

        oq = getattr(sot, "open_questions", None) or []
        unanswered_questions = len([q for q in oq if not getattr(q, "answered", False)])

        approvals = getattr(sot, "approvals_status", None) or {}
        approvals_status = {k: getattr(v, "value", str(v)) for k, v in approvals.items()}

    pending_approvals = (
        db.query(Approval.type, func.count(Approval.id))
        .filter(Approval.project_id == project_id, Approval.status == "pending")
        .group_by(Approval.type)
        .all()
    )
    pending_approvals_by_type = {t: int(c) for (t, c) in pending_approvals}

    # latest artifacts by type (optional helper for UI)
    artifact_types = ["brd", "prd", "sow", "server_details_client", "server_details_infra", "input_document"]
    latest_artifacts: dict[str, dict] = {}
    for t in artifact_types:
        a: Artifact | None = (
            db.query(Artifact)
            .filter(Artifact.project_id == project_id, Artifact.type == t)
            .order_by(Artifact.created_at.desc(), Artifact.version.desc())
            .first()
        )
        if a is not None:
            latest_artifacts[t] = {"artifact_id": a.id, "version": a.version, "created_at": a.created_at.isoformat()}

    phases = [{"id": p, "label": p, "status": _phase_statuses(current_phase)[p]} for p in _PHASES]

    details = {
        "run": {
            "latest_run_id": latest_run.id if latest_run else None,
            "status": latest_run.status if latest_run else None,
            "current_node": latest_run.current_node if latest_run else None,
        },
        "sot": {
            "current_phase": current_phase,
            "hosting_preference": hosting_preference,
            "rejection_feedback": rejection_feedback,
            "unanswered_questions": unanswered_questions,
            "approvals_status": approvals_status,
        },
        "approvals": {
            "pending_total": int(sum(pending_approvals_by_type.values())),
            "pending_by_type": pending_approvals_by_type,
        },
        "artifacts": latest_artifacts,
    }

    return {
        "id": project_id,
        "phases": phases,
        "details": details,
    }

