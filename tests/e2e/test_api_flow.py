"""E2E tests â€” Phase 2 (API-level, using httpx / TestClient).

Tests the full HTTP API layer end-to-end. Uses FastAPI's TestClient which
runs the real app with a real DB session (same Postgres as integration tests).

Covered flows:
  - Health endpoint
  - Projects CRUD
  - Traceability API (create link, list, matrix, delete)
  - OpenAPI schema structure
  - Run start + status check
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app, raise_server_exceptions=True)


# â”€â”€ Health â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def test_health_returns_200():
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


def test_health_includes_version():
    resp = client.get("/health")
    data = resp.json()
    assert "version" in data


# â”€â”€ Projects â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def test_create_project_returns_201():
    resp = client.post("/api/v1/projects", json={"name": "E2E Test Project"})
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert data["name"] == "E2E Test Project"


def test_get_project_returns_200():
    create_resp = client.post("/api/v1/projects", json={"name": "Get Test Project"})
    project_id = create_resp.json()["id"]

    get_resp = client.get(f"/api/v1/projects/{project_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == project_id


def test_list_projects_returns_list():
    resp = client.get("/api/v1/projects")
    assert resp.status_code == 200
    data = resp.json()
    # list endpoint returns {projects: [...], total: N}
    assert "projects" in data or isinstance(data, list)


def test_delete_project_returns_204():
    create_resp = client.post("/api/v1/projects", json={"name": "Delete Me E2E"})
    project_id = create_resp.json()["id"]

    del_resp = client.delete(f"/api/v1/projects/{project_id}")
    assert del_resp.status_code == 204

    get_resp = client.get(f"/api/v1/projects/{project_id}")
    assert get_resp.status_code == 404


def test_get_nonexistent_project_returns_404():
    resp = client.get("/api/v1/projects/999999")
    assert resp.status_code == 404


# â”€â”€ Traceability API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def test_create_trace_link_returns_201():
    project_resp = client.post("/api/v1/projects", json={"name": "Trace E2E Project"})
    project_id = project_resp.json()["id"]

    resp = client.post(
        f"/api/v1/projects/{project_id}/traceability",
        json={"requirement_id": "r1", "test_id": "TC-001"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["requirement_id"] == "r1"
    assert data["test_id"] == "TC-001"
    assert data["link_type"] == "test"
    assert data["project_id"] == project_id


def test_list_trace_links_returns_list():
    project_resp = client.post("/api/v1/projects", json={"name": "List Trace E2E"})
    project_id = project_resp.json()["id"]

    client.post(
        f"/api/v1/projects/{project_id}/traceability",
        json={"requirement_id": "r1", "test_id": "TC-001"},
    )
    client.post(
        f"/api/v1/projects/{project_id}/traceability",
        json={"requirement_id": "r2", "test_id": "TC-002"},
    )

    resp = client.get(f"/api/v1/projects/{project_id}/traceability")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 2


def test_traceability_matrix_endpoint():
    project_resp = client.post("/api/v1/projects", json={"name": "Matrix E2E Project"})
    project_id = project_resp.json()["id"]

    client.post(
        f"/api/v1/projects/{project_id}/traceability",
        json={"requirement_id": "r1", "test_id": "TC-001"},
    )
    client.post(
        f"/api/v1/projects/{project_id}/traceability",
        json={"requirement_id": "r1", "test_id": "TC-002"},
    )
    client.post(
        f"/api/v1/projects/{project_id}/traceability",
        json={"requirement_id": "r2", "test_id": "TC-003"},
    )

    resp = client.get(f"/api/v1/projects/{project_id}/traceability/matrix")
    assert resp.status_code == 200
    data = resp.json()

    assert "matrix" in data
    assert "coverage" in data
    assert "uncovered" in data
    assert "total_links" in data
    assert data["total_links"] == 3
    assert set(data["matrix"]["r1"]) == {"TC-001", "TC-002"}


def test_delete_trace_link_returns_204():
    project_resp = client.post("/api/v1/projects", json={"name": "Delete Link E2E"})
    project_id = project_resp.json()["id"]

    link_resp = client.post(
        f"/api/v1/projects/{project_id}/traceability",
        json={"requirement_id": "r1", "test_id": "TC-DEL"},
    )
    link_id = link_resp.json()["id"]

    del_resp = client.delete(f"/api/v1/traceability/{link_id}")
    assert del_resp.status_code == 204

    list_resp = client.get(f"/api/v1/projects/{project_id}/traceability")
    assert all(link["id"] != link_id for link in list_resp.json())


def test_delete_nonexistent_trace_link_returns_404():
    resp = client.delete("/api/v1/traceability/999999")
    assert resp.status_code == 404


def test_filter_trace_links_by_requirement():
    project_resp = client.post("/api/v1/projects", json={"name": "Filter E2E"})
    project_id = project_resp.json()["id"]

    client.post(f"/api/v1/projects/{project_id}/traceability",
                json={"requirement_id": "r1", "test_id": "TC-001"})
    client.post(f"/api/v1/projects/{project_id}/traceability",
                json={"requirement_id": "r2", "test_id": "TC-002"})

    resp = client.get(
        f"/api/v1/projects/{project_id}/traceability",
        params={"requirement_id": "r1"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["requirement_id"] == "r1"


# â”€â”€ Sessions â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def test_create_session_returns_201():
    project_resp = client.post("/api/v1/projects", json={"name": "Session E2E"})
    project_id = project_resp.json()["id"]

    resp = client.post(
        f"/api/v1/projects/{project_id}/sessions",
        json={"channel": "api"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert data["project_id"] == project_id


# â”€â”€ Runs â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def test_start_run_returns_run_with_status(tmp_path, monkeypatch):
    """Start a run via API and verify response has expected fields."""
    import app.artifacts.generator as gen_module
    monkeypatch.setattr(gen_module.settings, "ARTIFACTS_DIR", str(tmp_path), raising=False)

    project_resp = client.post("/api/v1/projects", json={"name": "Run E2E Project"})
    project_id = project_resp.json()["id"]

    resp = client.post(
        "/api/v1/runs/start",
        json={"project_id": project_id, "user_message": "Build an analytics platform"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert data["project_id"] == project_id
    assert data["status"] in ("waiting_user", "waiting_approval", "completed", "running")


def test_get_run_returns_run(tmp_path, monkeypatch):
    """GET /runs/{id} returns the run object."""
    import app.artifacts.generator as gen_module
    monkeypatch.setattr(gen_module.settings, "ARTIFACTS_DIR", str(tmp_path), raising=False)

    project_resp = client.post("/api/v1/projects", json={"name": "GetRun E2E"})
    project_id = project_resp.json()["id"]

    start_resp = client.post(
        "/api/v1/runs/start",
        json={"project_id": project_id, "user_message": "Test run"},
    )
    run_id = start_resp.json()["id"]

    get_resp = client.get(f"/api/v1/runs/{run_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == run_id


def test_get_nonexistent_run_returns_404():
    resp = client.get("/api/v1/runs/999999")
    assert resp.status_code == 404


# â”€â”€ OpenAPI â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def test_openapi_json_returns_200():
    resp = client.get("/openapi.json")
    assert resp.status_code == 200


def test_openapi_has_traceability_paths():
    resp = client.get("/openapi.json")
    paths = resp.json()["paths"]
    assert "/api/v1/projects/{project_id}/traceability" in paths
    assert "/api/v1/projects/{project_id}/traceability/matrix" in paths
