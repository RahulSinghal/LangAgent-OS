"""Session + message routes — Phase 1B."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas import (
    MessageCreate,
    MessageList,
    MessageResponse,
    SessionCreate,
    SessionResponse,
)
from app.services import projects as project_svc
from app.services import sessions as session_svc

router = APIRouter(tags=["sessions"])


@router.post(
    "/projects/{project_id}/sessions",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_session(
    project_id: int,
    body: SessionCreate,
    db: Session = Depends(get_db),
) -> SessionResponse:
    """Create a new session within a project."""
    project = project_svc.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    session = session_svc.create_session(db, project_id=project_id, channel=body.channel)
    return SessionResponse.model_validate(session)


@router.post(
    "/sessions/{session_id}/messages",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_message(
    session_id: int,
    body: MessageCreate,
    db: Session = Depends(get_db),
) -> MessageResponse:
    """Add a message to a session."""
    session = session_svc.get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    msg = session_svc.add_message(db, session_id=session_id, role=body.role, content=body.content)
    return MessageResponse.model_validate(msg)


@router.get("/sessions/{session_id}/messages", response_model=MessageList)
def get_messages(session_id: int, db: Session = Depends(get_db)) -> MessageList:
    """Get all messages in a session in chronological order."""
    session = session_svc.get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    messages = session_svc.get_messages(db, session_id)
    return MessageList(messages=[MessageResponse.model_validate(m) for m in messages])
