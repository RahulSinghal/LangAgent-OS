import os

from fastapi.testclient import TestClient


def _create_project_and_session(client: TestClient) -> tuple[int, int]:
    pr = client.post("/api/v1/projects", json={"name": "Test Project"}).json()
    sess = client.post(f"/api/v1/projects/{pr['id']}/sessions", json={"channel": "test"}).json()
    return pr["id"], sess["id"]


def test_prd_gate_requires_server_details_client_when_client_hosting() -> None:
    os.environ["USE_MOCK_AGENTS"] = "true"
    from app.main import create_app

    client = TestClient(create_app())
    project_id, session_id = _create_project_and_session(client)

    # Start run with message implying client hosting (default branch in mock)
    run = client.post(
        "/api/v1/runs/start",
        json={
            "project_id": project_id,
            "session_id": session_id,
            "user_message": "Client will host on their own server.",
        },
    ).json()

    # Should pause for approvals at PRD gate (PRD + server_details_client)
    run_status = client.get(f"/api/v1/runs/{run['id']}").json()
    assert run_status["status"] == "waiting_approval"

    approvals = client.get(f"/api/v1/runs/{run['id']}/approvals").json()
    types = {a["type"] for a in approvals}
    assert "prd" in types
    assert "server_details_client" in types
    assert "server_details_infra" not in types


def test_prd_gate_requires_server_details_infra_when_vendor_hosting() -> None:
    os.environ["USE_MOCK_AGENTS"] = "true"
    from app.main import create_app

    client = TestClient(create_app())
    project_id, session_id = _create_project_and_session(client)

    # Mock discovery sets hosting_preference="vendor" when it sees "our server"
    run = client.post(
        "/api/v1/runs/start",
        json={
            "project_id": project_id,
            "session_id": session_id,
            "user_message": "We can upload and run it on your server (our server).",
        },
    ).json()

    run_status = client.get(f"/api/v1/runs/{run['id']}").json()
    assert run_status["status"] == "waiting_approval"

    approvals = client.get(f"/api/v1/runs/{run['id']}/approvals").json()
    types = {a["type"] for a in approvals}
    assert "prd" in types
    assert "server_details_infra" in types
    assert "server_details_client" not in types

