"""Cross-project memory API routes.

Endpoints:
  POST   /memory/components                    — store a component manually
  GET    /memory/components                    — list / filter components
  GET    /memory/components/{id}               — fetch one component
  DELETE /memory/components/{id}               — delete a component
  POST   /memory/retrieve                      — tag-based retrieval (returns ranked list)
  POST   /memory/extract/{project_id}          — trigger auto-extraction from a project's latest SoT
  DELETE /memory/purge/{project_id}/auto       — purge stale auto-extracted rows before re-extraction
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.context_retrieval import (
    auto_extract_and_store,
    build_context_summary,
    delete_component,
    get_component,
    list_components,
    purge_auto_components,
    retrieve_relevant,
    store_component,
)

router = APIRouter(tags=["memory"])


# ── Schemas ───────────────────────────────────────────────────────────────────


class ComponentCreate(BaseModel):
    source_project_id: int | None = None
    component_type: str
    category: str = "general"
    name: str
    content: str
    tags: list[str] | None = None


class ComponentResponse(BaseModel):
    id: int
    source_project_id: int | None
    component_type: str
    category: str
    name: str
    content: str
    tags_json: list[str]
    source: str
    usage_count: int

    model_config = {"from_attributes": True}


class RetrieveRequest(BaseModel):
    tags: list[str]
    component_types: list[str] | None = None
    limit: int = 10
    min_overlap: int = 1
    include_summary: bool = False


class RetrieveResponse(BaseModel):
    components: list[dict]
    context_summary: str = ""


class ExtractResponse(BaseModel):
    extracted_count: int
    component_ids: list[int]


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post(
    "/memory/components",
    response_model=ComponentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Store a reusable component manually",
)
def create_component(
    body: ComponentCreate,
    db: Annotated[Session, Depends(get_db)],
) -> ComponentResponse:
    component = store_component(
        db,
        source_project_id=body.source_project_id,
        component_type=body.component_type,
        category=body.category,
        name=body.name,
        content=body.content,
        tags=body.tags,
        source="manual",
    )
    return ComponentResponse.model_validate(component)


@router.get(
    "/memory/components",
    response_model=list[ComponentResponse],
    summary="List stored components with optional filters",
)
def list_stored_components(
    db: Annotated[Session, Depends(get_db)],
    component_type: str | None = None,
    category: str | None = None,
    source_project_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[ComponentResponse]:
    rows = list_components(
        db,
        component_type=component_type,
        category=category,
        source_project_id=source_project_id,
        limit=limit,
        offset=offset,
    )
    return [ComponentResponse.model_validate(r) for r in rows]


@router.get(
    "/memory/components/{component_id}",
    response_model=ComponentResponse,
    summary="Fetch a single stored component",
)
def get_stored_component(
    component_id: int,
    db: Annotated[Session, Depends(get_db)],
) -> ComponentResponse:
    component = get_component(db, component_id)
    if component is None:
        raise HTTPException(status_code=404, detail=f"Component {component_id} not found")
    return ComponentResponse.model_validate(component)


@router.delete(
    "/memory/components/{component_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Delete a stored component",
)
def remove_component(
    component_id: int,
    db: Annotated[Session, Depends(get_db)],
) -> None:
    deleted = delete_component(db, component_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Component {component_id} not found")


@router.post(
    "/memory/retrieve",
    response_model=RetrieveResponse,
    summary="Retrieve relevant components by keyword tags",
)
def retrieve_components(
    body: RetrieveRequest,
    db: Annotated[Session, Depends(get_db)],
) -> RetrieveResponse:
    """Return stored components most relevant to the provided tags.

    Set *include_summary* to true to receive a formatted prompt-injection
    string (context_summary) ready to prepend to an agent system prompt.
    """
    components = retrieve_relevant(
        db,
        query_tags=body.tags,
        component_types=body.component_types,
        limit=body.limit,
        min_overlap=body.min_overlap,
    )
    summary = build_context_summary(components) if body.include_summary else ""
    return RetrieveResponse(components=components, context_summary=summary)


@router.post(
    "/memory/extract/{project_id}",
    response_model=ExtractResponse,
    summary="Auto-extract reusable patterns from a project's latest SoT snapshot",
)
def extract_from_project(
    project_id: int,
    db: Annotated[Session, Depends(get_db)],
) -> ExtractResponse:
    """Trigger on-demand extraction for a project.

    This is called automatically by end_node on completion, but can also be
    called manually via the API to back-fill older projects.
    """
    from app.db.models import Snapshot, Run
    from sqlalchemy import desc

    # Find the latest snapshot for this project
    latest = (
        db.query(Snapshot)
        .join(Run, Run.id == Snapshot.run_id)
        .filter(Run.project_id == project_id)
        .order_by(desc(Snapshot.created_at))
        .first()
    )
    if latest is None:
        raise HTTPException(
            status_code=404,
            detail=f"No snapshots found for project {project_id}",
        )

    # find the run_id for this snapshot so we record it on each component
    run_id = latest.run_id if latest else None
    stored = auto_extract_and_store(db, project_id, latest.state_jsonb, run_id=run_id)
    return ExtractResponse(
        extracted_count=len(stored),
        component_ids=[c.id for c in stored],
    )


class PurgeResponse(BaseModel):
    deleted_count: int


@router.delete(
    "/memory/purge/{project_id}/auto",
    response_model=PurgeResponse,
    summary="Purge all auto-extracted components for a project (keeps manual ones)",
)
def purge_project_auto_components(
    project_id: int,
    db: Annotated[Session, Depends(get_db)],
) -> PurgeResponse:
    """Delete stale auto-extracted knowledge for a project.

    Useful before triggering a manual re-extraction after a project revision,
    or when a project's direction has changed significantly.  Manual components
    (source='manual') are never affected.
    """
    count = purge_auto_components(db, project_id)
    return PurgeResponse(deleted_count=count)
