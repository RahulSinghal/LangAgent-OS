"""Project routes — Phase 1B."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas import (
    ProjectCreate,
    ProjectDashboardList,
    ProjectDashboardRow,
    ProjectList,
    ProjectResponse,
    ProjectStateGraphResponse,
)
from app.services import projects as svc
from app.services import sessions as session_svc
from app.services import dashboard as dashboard_svc
from app.services import state_graph as state_graph_svc

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(body: ProjectCreate, db: Session = Depends(get_db)) -> ProjectResponse:
    """Create a new project."""
    project = svc.create_project(db, name=body.name)
    return ProjectResponse.model_validate(project)


@router.get("", response_model=ProjectList)
def list_projects(db: Session = Depends(get_db)) -> ProjectList:
    """List all projects ordered by most recent first."""
    projects = svc.list_projects(db)
    return ProjectList(
        projects=[ProjectResponse.model_validate(p) for p in projects],
        total=len(projects),
    )


@router.get("/dashboard", response_model=ProjectDashboardList)
def list_projects_dashboard(db: Session = Depends(get_db)) -> ProjectDashboardList:
    """List projects with dashboard summary fields (state, artifacts, spend)."""
    rows = dashboard_svc.list_project_dashboard_rows(db)
    return ProjectDashboardList(
        projects=[ProjectDashboardRow.model_validate(r) for r in rows],
        total=len(rows),
    )


@router.get("/{project_id}/state_graph", response_model=ProjectStateGraphResponse)
def get_project_state_graph(project_id: int, db: Session = Depends(get_db)) -> ProjectStateGraphResponse:
    """Return a workflow phase graph + substates for a project."""
    project = svc.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    data = state_graph_svc.get_project_state_graph(db, project_id=project_id)
    return ProjectStateGraphResponse.model_validate(data)


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(project_id: int, db: Session = Depends(get_db)) -> ProjectResponse:
    """Get a single project by ID."""
    project = svc.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return ProjectResponse.model_validate(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: int, db: Session = Depends(get_db)) -> None:
    """Delete a project and all its data (cascade)."""
    deleted = svc.delete_project(db, project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")


@router.get("/{project_id}/messages")
def get_project_messages(project_id: int, db: Session = Depends(get_db)) -> dict:
    """Get all saved messages across sessions for a project."""
    project = svc.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    messages = session_svc.get_project_messages(db, project_id)
    latest_session = session_svc.get_latest_session_for_project(db, project_id)
    return {
        "project_id": project_id,
        "latest_session_id": latest_session.id if latest_session else None,
        "messages": [
            {
                "id": m.id,
                "session_id": m.session_id,
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
    }
