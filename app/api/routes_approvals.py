"""Approval routes — Phase 1F.

Endpoints:
  GET  /approvals/{approval_id}         — get approval record
  POST /approvals/{approval_id}/resolve — resolve an approval (approved|rejected)
  GET  /runs/{run_id}/approval          — get pending approval for a run
  GET  /runs/{run_id}/approvals         — list pending approvals for a run
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas import ApprovalResolveRequest, ApprovalResponse
from app.services import approvals as approval_svc

router = APIRouter(tags=["approvals"])


@router.get("/approvals/{approval_id}", response_model=ApprovalResponse)
def get_approval(approval_id: int, db: Session = Depends(get_db)) -> ApprovalResponse:
    """Get an approval record by ID."""
    approval = approval_svc.get_approval(db, approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail=f"Approval {approval_id} not found")
    return ApprovalResponse.model_validate(approval)


@router.post("/approvals/{approval_id}/resolve", response_model=ApprovalResponse)
def resolve_approval(
    approval_id: int,
    body: ApprovalResolveRequest,
    db: Session = Depends(get_db),
) -> ApprovalResponse:
    """Resolve a pending approval.

    Decision must be "approved" or "rejected".
    If the approval is linked to a run, the run is automatically resumed.
    """
    try:
        approval = approval_svc.resolve_approval(
            db,
            approval_id=approval_id,
            decision=body.decision,
            resolved_by=body.resolved_by,
            comments=body.comments,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return ApprovalResponse.model_validate(approval)


@router.get("/runs/{run_id}/approval", response_model=ApprovalResponse)
def get_pending_approval(run_id: int, db: Session = Depends(get_db)) -> ApprovalResponse:
    """Get the currently pending approval for a run, if any."""
    approval = approval_svc.get_pending_approval_for_run(db, run_id)
    if not approval:
        raise HTTPException(
            status_code=404,
            detail=f"No pending approval found for run {run_id}",
        )
    return ApprovalResponse.model_validate(approval)


@router.get("/runs/{run_id}/approvals", response_model=list[ApprovalResponse])
def list_pending_approvals(run_id: int, db: Session = Depends(get_db)) -> list[ApprovalResponse]:
    """List all pending approvals for a run, newest first."""
    approvals = approval_svc.list_pending_approvals_for_run(db, run_id)
    return [ApprovalResponse.model_validate(a) for a in approvals]
