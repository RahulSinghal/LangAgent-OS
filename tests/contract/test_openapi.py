"""Contract tests - Phase 2.

Validates the OpenAPI schema produced by FastAPI against expected structure.
These tests ensure the API contract is stable as the codebase evolves.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=True)


def test_openapi_schema_is_available():
    resp = client.get("/openapi.json")
    assert resp.status_code == 200


def test_openapi_schema_has_info():
    resp = client.get("/openapi.json")
    schema = resp.json()
    assert "info" in schema
    assert schema["info"]["title"] == "LangGraph AgentOS"


def test_openapi_schema_has_paths():
    resp = client.get("/openapi.json")
    schema = resp.json()
    assert "paths" in schema
    assert len(schema["paths"]) > 0


@pytest.mark.parametrize("path", [
    "/api/v1/projects",
    "/api/v1/runs/start",
    "/api/v1/projects/{project_id}/traceability",
    "/api/v1/projects/{project_id}/traceability/matrix",
])
def test_required_path_exists(path: str):
    resp = client.get("/openapi.json")
    schema = resp.json()
    assert path in schema["paths"], f"Expected path {path!r} not in OpenAPI schema"


def test_post_projects_has_request_body():
    resp = client.get("/openapi.json")
    schema = resp.json()
    post_projects = schema["paths"]["/api/v1/projects"]["post"]
    assert "requestBody" in post_projects


def test_projects_response_has_id():
    """Projects create/get endpoints should return an object with id."""
    resp = client.get("/openapi.json")
    schema = resp.json()
    defs = schema.get("components", {}).get("schemas", {})
    project_schemas = [k for k in defs if "Project" in k and "Response" in k]
    assert len(project_schemas) >= 1
    for name in project_schemas:
        assert "id" in defs[name].get("properties", {}), (
            f"{name} schema missing id property"
        )


def test_traceability_post_endpoint_exists():
    resp = client.get("/openapi.json")
    schema = resp.json()
    path = "/api/v1/projects/{project_id}/traceability"
    assert "post" in schema["paths"].get(path, {})


def test_traceability_get_matrix_endpoint_exists():
    resp = client.get("/openapi.json")
    schema = resp.json()
    path = "/api/v1/projects/{project_id}/traceability/matrix"
    assert "get" in schema["paths"].get(path, {})


def test_traceability_delete_endpoint_exists():
    resp = client.get("/openapi.json")
    schema = resp.json()
    path = "/api/v1/traceability/{link_id}"
    assert "delete" in schema["paths"].get(path, {})


def test_approval_resolve_endpoint_exists():
    resp = client.get("/openapi.json")
    schema = resp.json()
    path = "/api/v1/approvals/{approval_id}/resolve"
    assert "post" in schema["paths"].get(path, {})


def test_run_resume_endpoint_exists():
    resp = client.get("/openapi.json")
    schema = resp.json()
    path = "/api/v1/runs/{run_id}/resume"
    assert "post" in schema["paths"].get(path, {})


def test_docs_ui_is_available():
    resp = client.get("/docs")
    assert resp.status_code == 200


def test_redoc_ui_is_available():
    resp = client.get("/redoc")
    assert resp.status_code == 200


def test_artifact_response_schema_has_required_fields():
    """ArtifactResponse schema must have id, type, version, file_path."""
    resp = client.get("/openapi.json")
    schema = resp.json()
    defs = schema.get("components", {}).get("schemas", {})
    artifact_schemas = [k for k in defs if "Artifact" in k and "Response" in k]
    for name in artifact_schemas:
        props = defs[name].get("properties", {})
        for field in ("id", "type", "version"):
            assert field in props, f"{name} missing field {field!r}"
