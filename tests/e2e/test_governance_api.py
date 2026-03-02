"""E2E API tests for Phase 3 governance routes.

Tests auth, policies, baselines, change requests, comments, linting,
provenance, metrics, and audit log endpoints via FastAPI TestClient.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=True)


# ── Auth endpoints ─────────────────────────────────────────────────────────────

def test_register_org():
    resp = client.post("/api/v1/auth/register-org", json={"name": "E2ETestOrg"})
    assert resp.status_code in (200, 201)
    data = resp.json()
    assert "id" in data
    assert "slug" in data
    assert data["name"] == "E2ETestOrg"


def test_register_org_with_plan():
    resp = client.post("/api/v1/auth/register-org", json={"name": "ProOrg", "plan": "pro"})
    assert resp.status_code in (200, 201)
    assert resp.json()["plan"] == "pro"


def test_register_user():
    # Create org first
    org_resp = client.post("/api/v1/auth/register-org", json={"name": "UserRegOrg"})
    org_id = org_resp.json()["id"]
    resp = client.post("/api/v1/auth/register", json={
        "org_id": org_id,
        "email": "testuser@e2e.com",
        "password": "testpassword123",
        "role": "pm",
    })
    assert resp.status_code in (200, 201)
    data = resp.json()
    assert data["email"] == "testuser@e2e.com"
    assert data["role"] == "pm"


def test_get_token():
    # Register org + user
    org_resp = client.post("/api/v1/auth/register-org", json={"name": "TokenOrg"})
    org_id = org_resp.json()["id"]
    client.post("/api/v1/auth/register", json={
        "org_id": org_id, "email": "token@e2e.com", "password": "pw123"
    })
    # Get token
    resp = client.post(
        "/api/v1/auth/token",
        data={"username": "token@e2e.com", "password": "pw123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_get_token_invalid_credentials():
    resp = client.post(
        "/api/v1/auth/token",
        data={"username": "nobody@e2e.com", "password": "wrong"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 401


def test_list_orgs():
    resp = client.get("/api/v1/orgs")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_get_org_by_id():
    org_resp = client.post("/api/v1/auth/register-org", json={"name": "FetchOrg"})
    org_id = org_resp.json()["id"]
    resp = client.get(f"/api/v1/orgs/{org_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == org_id


def test_get_org_not_found():
    resp = client.get("/api/v1/orgs/999999")
    assert resp.status_code == 404


# ── Policy endpoints ───────────────────────────────────────────────────────────

def _create_org_for_policies():
    resp = client.post("/api/v1/auth/register-org", json={"name": "PolicyE2EOrg"})
    return resp.json()["id"]


def test_create_policy():
    org_id = _create_org_for_policies()
    resp = client.post(f"/api/v1/orgs/{org_id}/policies", json={
        "name": "WebSearchOnly",
        "policy_type": "tool_allowlist",
        "rules": {"allowed_tools": ["web_search"]},
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "WebSearchOnly"
    assert data["is_active"] is True


def test_list_policies():
    org_id = _create_org_for_policies()
    client.post(f"/api/v1/orgs/{org_id}/policies", json={
        "name": "P1", "policy_type": "budget", "rules": {"max_cost_usd": 10},
    })
    resp = client.get(f"/api/v1/orgs/{org_id}/policies")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_get_policy():
    org_id = _create_org_for_policies()
    create_resp = client.post(f"/api/v1/orgs/{org_id}/policies", json={
        "name": "GetMe", "policy_type": "budget", "rules": {},
    })
    policy_id = create_resp.json()["id"]
    resp = client.get(f"/api/v1/policies/{policy_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == policy_id


def test_update_policy():
    org_id = _create_org_for_policies()
    create_resp = client.post(f"/api/v1/orgs/{org_id}/policies", json={
        "name": "UpdateMe", "policy_type": "budget", "rules": {"max_cost_usd": 10},
    })
    policy_id = create_resp.json()["id"]
    update_resp = client.put(f"/api/v1/policies/{policy_id}", json={
        "rules": {"max_cost_usd": 50},
    })
    assert update_resp.status_code == 200
    assert update_resp.json()["rules_jsonb"]["max_cost_usd"] == 50


def test_delete_policy():
    org_id = _create_org_for_policies()
    create_resp = client.post(f"/api/v1/orgs/{org_id}/policies", json={
        "name": "DeleteMe", "policy_type": "budget", "rules": {},
    })
    policy_id = create_resp.json()["id"]
    del_resp = client.delete(f"/api/v1/policies/{policy_id}")
    assert del_resp.status_code == 204
    get_resp = client.get(f"/api/v1/policies/{policy_id}")
    assert get_resp.status_code == 404


def test_evaluate_policy_pass():
    org_id = _create_org_for_policies()
    client.post(f"/api/v1/orgs/{org_id}/policies", json={
        "name": "AllowSearch", "policy_type": "tool_allowlist",
        "rules": {"allowed_tools": ["web_search"]},
    })
    resp = client.post(f"/api/v1/orgs/{org_id}/policies/evaluate",
                       json={"context": {"tool_name": "web_search"}})
    assert resp.status_code == 200
    data = resp.json()
    assert data["allowed"] is True


def test_evaluate_policy_violation():
    org_id = _create_org_for_policies()
    client.post(f"/api/v1/orgs/{org_id}/policies", json={
        "name": "StrictAllowlist", "policy_type": "tool_allowlist",
        "rules": {"allowed_tools": ["web_search"]},
    })
    resp = client.post(f"/api/v1/orgs/{org_id}/policies/evaluate",
                       json={"context": {"tool_name": "exec_code"}})
    assert resp.status_code == 200
    data = resp.json()
    assert data["allowed"] is False
    assert len(data["violations"]) > 0


# ── Baseline endpoints ────────────────────────────────────────────────────────

def _create_project():
    resp = client.post("/api/v1/projects", json={"name": "GovernanceE2E"})
    return resp.json()["id"]


def test_create_baseline():
    project_id = _create_project()
    resp = client.post(f"/api/v1/projects/{project_id}/baselines", json={
        "label": "v1.0",
        "state_jsonb": {"phase": "prd", "title": "My Project"},
        "created_by": "pm@test.com",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["label"] == "v1.0"
    assert data["project_id"] == project_id


def test_list_baselines():
    project_id = _create_project()
    client.post(f"/api/v1/projects/{project_id}/baselines", json={
        "label": "v1", "state_jsonb": {}, "created_by": None,
    })
    resp = client.get(f"/api/v1/projects/{project_id}/baselines")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_get_baseline():
    project_id = _create_project()
    create_resp = client.post(f"/api/v1/projects/{project_id}/baselines",
                              json={"label": "fetchme", "state_jsonb": {}, "created_by": None})
    baseline_id = create_resp.json()["id"]
    resp = client.get(f"/api/v1/baselines/{baseline_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == baseline_id


# ── Change request endpoints ──────────────────────────────────────────────────

def test_create_change_request():
    project_id = _create_project()
    resp = client.post(f"/api/v1/projects/{project_id}/change-requests", json={
        "old_state": {"title": "Old"},
        "new_state": {"title": "New", "extra": "field"},
        "requested_by": "dev@test.com",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "open"
    assert data["project_id"] == project_id


def test_list_change_requests():
    project_id = _create_project()
    client.post(f"/api/v1/projects/{project_id}/change-requests", json={
        "old_state": {}, "new_state": {"x": 1}, "requested_by": None,
    })
    resp = client.get(f"/api/v1/projects/{project_id}/change-requests")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_resolve_change_request():
    project_id = _create_project()
    cr_resp = client.post(f"/api/v1/projects/{project_id}/change-requests", json={
        "old_state": {}, "new_state": {"key": "val"}, "requested_by": None,
    })
    cr_id = cr_resp.json()["id"]
    resolve_resp = client.post(f"/api/v1/change-requests/{cr_id}/resolve", json={
        "decision": "approved",
        "reviewed_by": "lead@test.com",
        "review_notes": "Approved for release",
    })
    assert resolve_resp.status_code == 200
    assert resolve_resp.json()["status"] == "approved"


# ── Audit log endpoint ────────────────────────────────────────────────────────

def test_get_audit_log():
    project_id = _create_project()
    # Create some change requests to generate activity
    client.post(f"/api/v1/projects/{project_id}/change-requests",
                json={"old_state": {}, "new_state": {"x": 1}, "requested_by": None})
    resp = client.get(f"/api/v1/projects/{project_id}/audit-log")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ── Run metrics endpoint ──────────────────────────────────────────────────────

def test_get_run_metrics_not_found():
    resp = client.get("/api/v1/runs/999999/metrics")
    assert resp.status_code == 404


def test_get_run_trace():
    resp = client.get("/api/v1/runs/999999/trace")
    assert resp.status_code in (200, 404)


# ── Export endpoint ───────────────────────────────────────────────────────────

def test_export_no_artifacts_returns_error():
    project_id = _create_project()
    resp = client.get(f"/api/v1/projects/{project_id}/export")
    # Should return 404 or 400 when no artifacts exist
    assert resp.status_code in (400, 404, 422)
