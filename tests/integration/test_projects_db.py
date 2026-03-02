"""Phase 1B integration tests — real PostgreSQL required.

Run with: pytest tests/integration -v
(Docker DB must be up: docker compose up -d)
"""

import pytest
from sqlalchemy.orm import Session

from app.services.projects import create_project, get_project, list_projects, delete_project
from app.services.sessions import create_session, add_message, get_messages


# ── Project CRUD ──────────────────────────────────────────────────────────────

def test_create_project(db: Session):
    project = create_project(db, name="Test Project Alpha")
    assert project.id is not None
    assert project.name == "Test Project Alpha"
    assert project.created_at is not None


def test_get_project(db: Session):
    project = create_project(db, name="Fetch Me")
    fetched = get_project(db, project.id)
    assert fetched is not None
    assert fetched.id == project.id
    assert fetched.name == "Fetch Me"


def test_get_project_not_found(db: Session):
    result = get_project(db, project_id=999999)
    assert result is None


def test_list_projects(db: Session):
    create_project(db, name="List Project 1")
    create_project(db, name="List Project 2")
    projects = list_projects(db)
    assert len(projects) >= 2
    names = [p.name for p in projects]
    assert "List Project 1" in names
    assert "List Project 2" in names


def test_delete_project(db: Session):
    project = create_project(db, name="Delete Me")
    pid = project.id
    deleted = delete_project(db, pid)
    assert deleted is True
    assert get_project(db, pid) is None


def test_delete_project_not_found(db: Session):
    result = delete_project(db, project_id=999999)
    assert result is False


# ── Session + Message ─────────────────────────────────────────────────────────

def test_create_session(db: Session):
    project = create_project(db, name="Session Owner")
    session = create_session(db, project_id=project.id, channel="api")
    assert session.id is not None
    assert session.project_id == project.id
    assert session.channel == "api"


def test_add_and_get_messages(db: Session):
    project = create_project(db, name="Message Owner")
    session = create_session(db, project_id=project.id)

    msg1 = add_message(db, session_id=session.id, role="user", content="Hello")
    msg2 = add_message(db, session_id=session.id, role="assistant", content="Hi there!")

    messages = get_messages(db, session_id=session.id)
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[0].content == "Hello"
    assert messages[1].role == "assistant"
    assert messages[1].content == "Hi there!"


def test_cascade_delete_removes_sessions(db: Session):
    """Deleting a project cascades to its sessions."""
    project = create_project(db, name="Cascade Owner")
    session = create_session(db, project_id=project.id)
    sid = session.id

    delete_project(db, project.id)

    from app.db.models import Session as SessionModel
    gone = db.get(SessionModel, sid)
    assert gone is None
