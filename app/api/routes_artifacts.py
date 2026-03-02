"""Artifact routes — Phase 1F.

Endpoints:
  GET /projects/{project_id}/artifacts   — list all artifacts for a project
  GET /artifacts/{artifact_id}           — get artifact metadata
  GET /artifacts/{artifact_id}/content   — get rendered Markdown content
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas import ArtifactList, ArtifactResponse
from app.services import artifacts as artifact_svc
from app.services import projects as project_svc

router = APIRouter(tags=["artifacts"])


@router.get("/projects/{project_id}/artifacts", response_model=ArtifactList)
def list_artifacts(project_id: int, db: Session = Depends(get_db)) -> ArtifactList:
    """List all artifacts for a project."""
    project = project_svc.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    artifacts = artifact_svc.list_artifacts(db, project_id)
    return ArtifactList(artifacts=[ArtifactResponse.model_validate(a) for a in artifacts])


@router.get("/artifacts/{artifact_id}", response_model=ArtifactResponse)
def get_artifact(artifact_id: int, db: Session = Depends(get_db)) -> ArtifactResponse:
    """Get artifact metadata by ID."""
    artifact = artifact_svc.get_artifact(db, artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail=f"Artifact {artifact_id} not found")
    return ArtifactResponse.model_validate(artifact)


@router.get("/artifacts/{artifact_id}/content")
def get_artifact_content(artifact_id: int, db: Session = Depends(get_db)) -> dict:
    """Get the rendered Markdown content of an artifact."""
    try:
        content = artifact_svc.read_artifact_content(db, artifact_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"artifact_id": artifact_id, "content": content}
