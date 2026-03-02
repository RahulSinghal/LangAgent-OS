"""Session + message service — Phase 1B."""

from sqlalchemy.orm import Session as DbSession
from sqlalchemy import asc

from app.db.models import Message, Session


def create_session(db: DbSession, project_id: int, channel: str = "api") -> Session:
    session = Session(project_id=project_id, channel=channel)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_session(db: DbSession, session_id: int) -> Session | None:
    return db.get(Session, session_id)


def add_message(db: DbSession, session_id: int, role: str, content: str) -> Message:
    msg = Message(session_id=session_id, role=role, content=content)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def get_messages(db: DbSession, session_id: int) -> list[Message]:
    return (
        db.query(Message)
        .filter(Message.session_id == session_id)
        .order_by(Message.created_at)
        .all()
    )


def get_project_messages(db: DbSession, project_id: int) -> list[Message]:
    """Get all messages across all sessions for a project, in time order."""
    return (
        db.query(Message)
        .join(Session, Session.id == Message.session_id)
        .filter(Session.project_id == project_id)
        .order_by(asc(Message.created_at), asc(Message.id))
        .all()
    )


def get_latest_session_for_project(db: DbSession, project_id: int) -> Session | None:
    return (
        db.query(Session)
        .filter(Session.project_id == project_id)
        .order_by(Session.created_at.desc())
        .first()
    )
