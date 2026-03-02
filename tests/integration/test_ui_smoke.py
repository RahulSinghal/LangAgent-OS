import os

from fastapi.testclient import TestClient


def test_ui_root_serves_html() -> None:
    # Ensure deterministic mode doesn't matter for UI-only routes
    os.environ.pop("USE_MOCK_AGENTS", None)
    from app.main import create_app

    client = TestClient(create_app())
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert "AgentOS" in r.text
    # Dashboard-first UI (project dropdown removed)
    assert "dashboardView" in r.text


def test_ui_static_assets_served() -> None:
    from app.main import create_app

    client = TestClient(create_app())
    r = client.get("/ui/app.js")
    assert r.status_code == 200
    assert "API_PREFIX" in r.text


def test_document_extract_text_plain() -> None:
    from app.main import create_app

    client = TestClient(create_app())
    content = b"Hello from a test document."
    files = {"file": ("test.txt", content, "text/plain")}
    r = client.post("/api/v1/documents/extract", files=files)
    assert r.status_code == 200
    data = r.json()
    assert data["filename"] == "test.txt"
    assert "Hello from a test document." in data["text"]

