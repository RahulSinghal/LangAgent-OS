"""SoT routes — helper endpoints for UI and debugging.

Endpoints:
  GET /runs/{run_id}/sot  — return latest SoT snapshot for a run
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services import runs as run_svc
from app.services.snapshots import load_latest_snapshot

router = APIRouter(tags=["sot"])


@router.get("/runs/{run_id}/sot")
def get_latest_sot(run_id: int, db: Session = Depends(get_db)) -> dict:
    """Return the latest SoT snapshot for a run.

    The UI uses this to display the latest unanswered discovery question and
    general run context without requiring the workflow to persist bot_response.
    """
    run = run_svc.get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    sot = load_latest_snapshot(db, run_id)
    if sot is None:
        raise HTTPException(status_code=404, detail=f"No snapshot found for run {run_id}")

    unanswered = [q.question for q in sot.open_questions if not q.answered]
    return {
        "run_id": run_id,
        "sot": sot.model_dump(mode="json"),
        "unanswered_questions": unanswered,
    }

