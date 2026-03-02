"""Unit tests for Pydantic schemas — no DB required."""

import pytest
from pydantic import ValidationError

from app.schemas import (
    ApprovalResolveRequest,
    MessageCreate,
    ProjectCreate,
    RunStartRequest,
)


# ── ProjectCreate ──────────────────────────────────────────────────────────────

def test_project_create_valid():
    p = ProjectCreate(name="My Project")
    assert p.name == "My Project"


def test_project_create_strips_whitespace():
    p = ProjectCreate(name="  Padded  ")
    assert p.name == "Padded"


def test_project_create_empty_name_raises():
    with pytest.raises(ValidationError):
        ProjectCreate(name="   ")


# ── MessageCreate ──────────────────────────────────────────────────────────────

def test_message_create_default_role():
    m = MessageCreate(content="Hello")
    assert m.role == "user"


def test_message_create_valid_roles():
    for role in ("user", "assistant", "system"):
        m = MessageCreate(role=role, content="test")
        assert m.role == role


def test_message_create_invalid_role():
    with pytest.raises(ValidationError):
        MessageCreate(role="admin", content="test")


def test_message_create_empty_content():
    with pytest.raises(ValidationError):
        MessageCreate(content="   ")


# ── ApprovalResolveRequest ────────────────────────────────────────────────────

def test_approval_resolve_approved():
    a = ApprovalResolveRequest(decision="approved", resolved_by="alice")
    assert a.decision == "approved"


def test_approval_resolve_rejected():
    a = ApprovalResolveRequest(decision="rejected")
    assert a.decision == "rejected"


def test_approval_resolve_invalid_decision():
    with pytest.raises(ValidationError):
        ApprovalResolveRequest(decision="maybe")


# ── RunStartRequest ───────────────────────────────────────────────────────────

def test_run_start_request():
    r = RunStartRequest(project_id=1, session_id=2, user_message="Start")
    assert r.project_id == 1
    assert r.session_id == 2


def test_run_start_request_optional_fields():
    r = RunStartRequest(project_id=5)
    assert r.session_id is None
    assert r.user_message is None
