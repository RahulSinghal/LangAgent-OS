"""Phase 1A — config unit tests."""

from app.core.config import Settings


def test_database_url_built_correctly():
    """DATABASE_URL is correctly assembled from individual Postgres settings."""
    s = Settings(
        POSTGRES_USER="testuser",
        POSTGRES_PASSWORD="testpass",
        POSTGRES_HOST="testhost",
        POSTGRES_PORT=5555,
        POSTGRES_DB="testdb",
    )
    assert s.DATABASE_URL == (
        "postgresql+psycopg2://testuser:testpass@testhost:5555/testdb"
    )


def test_default_api_prefix():
    s = Settings()
    assert s.API_PREFIX == "/api/v1"


def test_default_llm_provider():
    s = Settings()
    assert s.LLM_PROVIDER == "openai"
