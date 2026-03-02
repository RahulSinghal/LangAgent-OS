"""Phase 1A smoke test — verifies the app starts and health endpoint responds."""

from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

from app.main import app


def _mock_db():
    """Return a mock DB session that satisfies get_db dependency."""
    db = MagicMock()
    db.execute.return_value = MagicMock()
    return db


def test_health_returns_ok():
    """Health endpoint returns status=ok without a real DB connection."""
    with patch("app.api.routes_health.get_db") as mock_get_db:
        mock_get_db.return_value = iter([_mock_db()])
        client = TestClient(app)
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert "uptime_seconds" in body


def test_health_includes_version():
    """Health endpoint returns the app version from settings."""
    from app.core.config import settings

    with patch("app.api.routes_health.get_db") as mock_get_db:
        mock_get_db.return_value = iter([_mock_db()])
        client = TestClient(app)
        response = client.get("/health")

    assert response.json()["version"] == settings.APP_VERSION


def test_docs_available():
    """OpenAPI docs endpoint is accessible."""
    client = TestClient(app)
    response = client.get("/docs")
    assert response.status_code == 200
