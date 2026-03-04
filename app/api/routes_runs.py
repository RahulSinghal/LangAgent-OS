"""Run engine routes — Phase 1E.

Endpoints:
  POST /runs/start           — start a new run
  GET  /runs/{run_id}        — get run status
  POST /runs/{run_id}/resume — resume a paused run
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas import RunResumeRequest, RunResponse, RunStartRequest
from app.services import runs as run_svc
from app.services import projects as project_svc

router = APIRouter(prefix="/runs", tags=["runs"])


@router.post("/start", response_model=RunResponse, status_code=status.HTTP_201_CREATED)
def start_run(body: RunStartRequest, db: Session = Depends(get_db)) -> RunResponse:
    """Start a new run for a project.

    The graph executes synchronously until it pauses (waiting_user /
    waiting_approval) or completes.
    """
    project = project_svc.get_project(db, body.project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {body.project_id} not found")

    run = run_svc.start_run(
        db,
        project_id=body.project_id,
        session_id=body.session_id,
        user_message=body.user_message,
        document_content=body.document_content,
        document_filename=body.document_filename,
    )
    return RunResponse.model_validate(run)


@router.get("/{run_id}", response_model=RunResponse)
def get_run(run_id: int, db: Session = Depends(get_db)) -> RunResponse:
    """Get the current status and metadata for a run."""
    run = run_svc.get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return RunResponse.model_validate(run)


@router.post("/{run_id}/resume", response_model=RunResponse)
def resume_run(
    run_id: int,
    body: RunResumeRequest,
    db: Session = Depends(get_db),
) -> RunResponse:
    """Resume a paused run.

    Supply user_message when the run is waiting_user.
    The approval resolution endpoint handles waiting_approval resumes.
    """
    run = run_svc.get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    if run.status not in ("waiting_user", "waiting_approval"):
        raise HTTPException(
            status_code=409,
            detail=f"Run {run_id} is not paused (status={run.status!r})",
        )

    try:
        updated = run_svc.resume_run(
            db,
            run_id,
            user_message=body.user_message,
            document_content=body.document_content,
            document_filename=body.document_filename,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return RunResponse.model_validate(updated)
