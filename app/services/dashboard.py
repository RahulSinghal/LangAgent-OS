from __future__ import annotations

from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import Approval, Artifact, Message, Project, Run, RunMetrics, Session as DbSession


def list_project_dashboard_rows(db: Session) -> list[dict]:
    """Return per-project summary rows for the UI dashboard."""
    projects = db.query(Project).order_by(Project.created_at.desc()).all()

    rows: list[dict] = []
    artifact_types = [
        "brd",
        "prd",
        "sow",
        "server_details_client",
        "server_details_infra",
        "input_document",
        "code",
    ]

    for p in projects:
        latest_run = (
            db.query(Run)
            .filter(Run.project_id == p.id)
            .order_by(Run.created_at.desc())
            .first()
        )

        pending_approvals = int(
            db.query(func.count(Approval.id))
            .filter(Approval.project_id == p.id, Approval.status == "pending")
            .scalar()
            or 0
        )

        total_tokens, total_cost_usd, total_runtime_ms = (
            db.query(
                func.coalesce(func.sum(RunMetrics.total_tokens), 0),
                func.coalesce(func.sum(RunMetrics.total_cost_usd), 0.0),
                func.coalesce(func.sum(RunMetrics.total_latency_ms), 0),
            )
            .filter(RunMetrics.project_id == p.id)
            .one()
        )

        last_activity: datetime | None = (
            db.query(func.max(Message.created_at))
            .join(DbSession, Message.session_id == DbSession.id)
            .filter(DbSession.project_id == p.id)
            .scalar()
        )

        artifacts: dict[str, dict] = {}
        for t in artifact_types:
            a = (
                db.query(Artifact)
                .filter(Artifact.project_id == p.id, Artifact.type == t)
                .order_by(Artifact.created_at.desc(), Artifact.version.desc())
                .first()
            )
            if a is not None:
                artifacts[t] = {
                    "id": a.id,
                    "type": a.type,
                    "created_at": a.created_at,
                    "version": a.version,
                }

        current_state = None
        run_status = None
        latest_run_id = None
        if latest_run is not None:
            latest_run_id = latest_run.id
            current_state = latest_run.current_node or latest_run.status
            run_status = latest_run.status

        rows.append(
            {
                "project_id": p.id,
                "name": p.name,
                "created_at": p.created_at,
                "latest_run_id": latest_run_id,
                "current_state": current_state,
                "run_status": run_status,
                "pending_approvals": pending_approvals,
                "artifacts": artifacts,
                "tokens_spent": int(total_tokens or 0),
                "cost_usd": float(total_cost_usd or 0.0),
                "system_runtime_ms": int(total_runtime_ms or 0),
                "system_hours": float(total_runtime_ms or 0) / 3_600_000.0,
                "last_activity_at": last_activity,
            }
        )

    return rows

