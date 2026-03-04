"""Traceability matrix API routes — Phase 2.

Endpoints:
  POST   /projects/{project_id}/traceability          — create a trace link
  GET    /projects/{project_id}/traceability          — list all trace links
  GET    /projects/{project_id}/traceability/matrix   — full coverage matrix
  DELETE /traceability/{link_id}                      — remove a trace link
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.traceability import (
    create_trace_link,
    delete_trace_link,
    get_traceability_matrix,
    list_trace_links,
)

router = APIRouter(tags=["traceability"])


# ── Request / Response schemas ────────────────────────────────────────────────

class TraceLinkCreate(BaseModel):
    requirement_id: str
    test_id: str
    link_type: str = "test"
    milestone_id: str | None = None
    eval_type: str | None = None
    notes: str | None = None


class TraceLinkResponse(BaseModel):
    id: int
    project_id: int
    requirement_id: str
    test_id: str
    link_type: str
    milestone_id: str | None = None
    eval_type: str | None = None
    source: str = "manual"
    notes: str | None = None

    model_config = {"from_attributes": True}


class TraceabilityMatrixResponse(BaseModel):
    matrix: dict[str, list[str]]
    coverage: dict[str, int]
    uncovered: list[str]
    total_links: int
    summary_stats: dict


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "/projects/{project_id}/traceability",
    response_model=TraceLinkResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a trace link between a requirement and a test",
)
def create_link(
    project_id: int,
    body: TraceLinkCreate,
    db: Annotated[Session, Depends(get_db)],
) -> TraceLinkResponse:
    link = create_trace_link(
        db,
        project_id=project_id,
        requirement_id=body.requirement_id,
        test_id=body.test_id,
        link_type=body.link_type,
        milestone_id=body.milestone_id,
        eval_type=body.eval_type,
        notes=body.notes,
    )
    return TraceLinkResponse.model_validate(link)


@router.get(
    "/projects/{project_id}/traceability",
    response_model=list[TraceLinkResponse],
    summary="List all trace links for a project",
)
def list_links(
    project_id: int,
    db: Annotated[Session, Depends(get_db)],
    requirement_id: str | None = None,
) -> list[TraceLinkResponse]:
    links = list_trace_links(db, project_id, requirement_id=requirement_id)
    return [TraceLinkResponse.model_validate(link) for link in links]


@router.get(
    "/projects/{project_id}/traceability/matrix",
    response_model=TraceabilityMatrixResponse,
    summary="Get full traceability coverage matrix for a project",
)
def traceability_matrix(
    project_id: int,
    db: Annotated[Session, Depends(get_db)],
) -> TraceabilityMatrixResponse:
    matrix_data = get_traceability_matrix(db, project_id)
    return TraceabilityMatrixResponse(**matrix_data)


@router.delete(
    "/traceability/{link_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Delete a trace link by ID",
)
def remove_link(
    link_id: int,
    db: Annotated[Session, Depends(get_db)],
):
    deleted = delete_trace_link(db, link_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Trace link {link_id} not found")
