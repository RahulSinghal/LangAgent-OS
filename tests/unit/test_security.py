"""Unit tests for JWT security utilities — Phase 3B.

Tests: hash_password, verify_password, create_access_token,
       decode_access_token, get_current_user, require_role.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi import HTTPException

from app.core.security import (
    TokenData,
    create_access_token,
    decode_access_token,
    get_current_user,
    hash_password,
    require_role,
    verify_password,
)


# ── Password hashing ──────────────────────────────────────────────────────────

def test_hash_password_returns_string():
    h = hash_password("mysecret")
    assert isinstance(h, str)
    assert len(h) > 20


def test_hash_password_not_plaintext():
    h = hash_password("mysecret")
    assert "mysecret" not in h


def test_verify_password_correct():
    h = hash_password("correct")
    assert verify_password("correct", h) is True


def test_verify_password_wrong():
    h = hash_password("correct")
    assert verify_password("wrong", h) is False


def test_verify_password_empty():
    h = hash_password("secret")
    assert verify_password("", h) is False


def test_hash_different_passwords_different_hashes():
    h1 = hash_password("alpha")
    h2 = hash_password("beta")
    assert h1 != h2


def test_same_password_different_hashes_each_time():
    """bcrypt salt ensures same password hashes differently."""
    h1 = hash_password("same")
    h2 = hash_password("same")
    assert h1 != h2  # different salts
    # but both verify correctly
    assert verify_password("same", h1)
    assert verify_password("same", h2)


# ── JWT creation ──────────────────────────────────────────────────────────────

def test_create_access_token_returns_string():
    token = create_access_token("user@test.com", org_id=1, role="admin")
    assert isinstance(token, str)
    assert len(token) > 10


def test_create_access_token_with_custom_expiry():
    token = create_access_token(
        "user@test.com", org_id=5, role="viewer",
        expires_delta=timedelta(hours=2),
    )
    assert isinstance(token, str)


# ── JWT decoding ──────────────────────────────────────────────────────────────

def test_decode_access_token_round_trip():
    token = create_access_token("alice@test.com", org_id=3, role="pm")
    payload = decode_access_token(token)
    assert payload["sub"] == "alice@test.com"
    assert payload["org_id"] == 3
    assert payload["role"] == "pm"


def test_decode_access_token_invalid_raises_401():
    with pytest.raises(HTTPException) as exc_info:
        decode_access_token("not.a.valid.jwt")
    assert exc_info.value.status_code == 401


def test_decode_access_token_tampered_raises_401():
    token = create_access_token("bob@test.com", org_id=1, role="admin")
    # Tamper with the signature
    tampered = token[:-4] + "XXXX"
    with pytest.raises(HTTPException):
        decode_access_token(tampered)


def test_decode_expired_token_raises_401():
    token = create_access_token(
        "charlie@test.com", org_id=2, role="viewer",
        expires_delta=timedelta(seconds=-1),   # already expired
    )
    with pytest.raises(HTTPException) as exc_info:
        decode_access_token(token)
    assert exc_info.value.status_code == 401


# ── get_current_user dependency ───────────────────────────────────────────────

def test_get_current_user_returns_token_data():
    token = create_access_token("diana@test.com", org_id=7, role="analyst")
    td = get_current_user(token)
    assert isinstance(td, TokenData)
    assert td.email == "diana@test.com"
    assert td.org_id == 7
    assert td.role == "analyst"


def test_get_current_user_invalid_token_raises_401():
    with pytest.raises(HTTPException) as exc_info:
        get_current_user("bad-token")
    assert exc_info.value.status_code == 401


# ── require_role dependency ───────────────────────────────────────────────────

def test_require_role_allowed():
    token = create_access_token("eve@test.com", org_id=1, role="admin")
    td = get_current_user(token)
    dep = require_role("admin", "pm")
    result = dep(td)
    assert result.role == "admin"


def test_require_role_blocked_raises_403():
    token = create_access_token("frank@test.com", org_id=1, role="viewer")
    td = get_current_user(token)
    dep = require_role("admin")
    with pytest.raises(HTTPException) as exc_info:
        dep(td)
    assert exc_info.value.status_code == 403


def test_require_role_multiple_allowed():
    for role in ("admin", "pm", "analyst"):
        token = create_access_token(f"{role}@test.com", org_id=1, role=role)
        td = get_current_user(token)
        dep = require_role("admin", "pm", "analyst")
        result = dep(td)
        assert result.role == role


def test_token_data_repr():
    td = TokenData(email="x@y.com", org_id=1, role="viewer")
    assert "x@y.com" in repr(td)
    assert "viewer" in repr(td)
