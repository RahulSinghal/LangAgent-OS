"""Integration tests for auth service — Phase 3B.

Tests organisation CRUD, user CRUD, authentication, and JWT token flow.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.services.auth import (
    authenticate_user,
    create_org,
    create_user,
    get_org,
    get_user_by_email,
    list_orgs,
    login_for_access_token,
)
from app.core.security import decode_access_token


# ── Organization CRUD ─────────────────────────────────────────────────────────

def test_create_org_basic(db: Session):
    org = create_org(db, name="Acme Corp")
    assert org.id is not None
    assert org.name == "Acme Corp"
    assert org.plan == "free"
    assert org.slug is not None
    assert len(org.slug) > 0


def test_create_org_slug_derived_from_name(db: Session):
    org = create_org(db, name="Blue Ocean Analytics")
    assert "blue" in org.slug
    assert " " not in org.slug  # no spaces


def test_create_org_with_enterprise_plan(db: Session):
    org = create_org(db, name="BigCo Ltd", plan="enterprise")
    assert org.plan == "enterprise"


def test_create_org_slug_unique(db: Session):
    org1 = create_org(db, name="Duplicate Name")
    org2 = create_org(db, name="Duplicate Name")
    assert org1.slug != org2.slug


def test_get_org_returns_org(db: Session):
    org = create_org(db, name="GetMe Corp")
    fetched = get_org(db, org.id)
    assert fetched is not None
    assert fetched.id == org.id
    assert fetched.name == "GetMe Corp"


def test_get_org_nonexistent_returns_none(db: Session):
    result = get_org(db, org_id=999999)
    assert result is None


def test_list_orgs_returns_list(db: Session):
    create_org(db, name="ListOrg Alpha")
    create_org(db, name="ListOrg Beta")
    orgs = list_orgs(db)
    assert isinstance(orgs, list)
    assert len(orgs) >= 2


# ── User CRUD ─────────────────────────────────────────────────────────────────

def test_create_user_basic(db: Session):
    org = create_org(db, name="UserTest Org")
    user = create_user(db, org_id=org.id, email="alice@test.com", password="secret123")
    assert user.id is not None
    assert user.email == "alice@test.com"
    assert user.org_id == org.id
    assert user.role == "viewer"
    assert user.is_active is True


def test_create_user_password_hashed(db: Session):
    org = create_org(db, name="HashTest Org")
    user = create_user(db, org_id=org.id, email="hash@test.com", password="plaintext")
    assert user.hashed_password != "plaintext"
    assert user.hashed_password is not None
    assert len(user.hashed_password) > 10


def test_create_user_with_admin_role(db: Session):
    org = create_org(db, name="AdminRole Org")
    user = create_user(db, org_id=org.id, email="admin@test.com", password="pw", role="admin")
    assert user.role == "admin"


def test_get_user_by_email_found(db: Session):
    org = create_org(db, name="EmailLookup Org")
    create_user(db, org_id=org.id, email="lookup@test.com", password="pw")
    found = get_user_by_email(db, "lookup@test.com")
    assert found is not None
    assert found.email == "lookup@test.com"


def test_get_user_by_email_not_found(db: Session):
    result = get_user_by_email(db, "nonexistent@test.com")
    assert result is None


# ── Authentication ────────────────────────────────────────────────────────────

def test_authenticate_user_valid_credentials(db: Session):
    org = create_org(db, name="Auth Org Valid")
    create_user(db, org_id=org.id, email="valid@test.com", password="correct_pass")
    user = authenticate_user(db, "valid@test.com", "correct_pass")
    assert user is not None
    assert user.email == "valid@test.com"


def test_authenticate_user_wrong_password(db: Session):
    org = create_org(db, name="Auth Org Wrong")
    create_user(db, org_id=org.id, email="wrong@test.com", password="actual_pass")
    user = authenticate_user(db, "wrong@test.com", "wrong_pass")
    assert user is None


def test_authenticate_user_nonexistent_email(db: Session):
    user = authenticate_user(db, "nobody@test.com", "any_pass")
    assert user is None


# ── Token issuance ────────────────────────────────────────────────────────────

def test_login_for_access_token_valid(db: Session):
    org = create_org(db, name="TokenOrg")
    create_user(db, org_id=org.id, email="tokenuser@test.com", password="tokenpass", role="pm")
    token = login_for_access_token(db, "tokenuser@test.com", "tokenpass")
    assert isinstance(token, str)
    assert len(token) > 10


def test_login_token_payload_correct(db: Session):
    org = create_org(db, name="PayloadOrg")
    create_user(db, org_id=org.id, email="payload@test.com", password="pw", role="analyst")
    token = login_for_access_token(db, "payload@test.com", "pw")
    payload = decode_access_token(token)
    assert payload["sub"] == "payload@test.com"
    assert payload["role"] == "analyst"
    assert payload["org_id"] == org.id


def test_login_invalid_credentials_raises_401(db: Session):
    org = create_org(db, name="BadLogin Org")
    create_user(db, org_id=org.id, email="badlogin@test.com", password="correct")
    with pytest.raises(HTTPException) as exc_info:
        login_for_access_token(db, "badlogin@test.com", "wrong")
    assert exc_info.value.status_code == 401


def test_login_nonexistent_user_raises_401(db: Session):
    with pytest.raises(HTTPException) as exc_info:
        login_for_access_token(db, "ghost@test.com", "any")
    assert exc_info.value.status_code == 401
