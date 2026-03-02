"""E2E test fixtures — ensures DB tables exist for the full app TestClient."""

import os

# Force E2E tests onto an isolated DB to avoid clobbering dev/server DB.
os.environ.setdefault("POSTGRES_DB", "agentosdb_e2e")

import pytest
from sqlalchemy import text
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.session import Base
import app.db.models  # noqa: F401 — registers all models on Base


def _ensure_database_exists(db_name: str) -> None:
    admin_url = (
        f"postgresql+psycopg2://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
        f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/postgres"
    )
    admin_engine = create_engine(admin_url, echo=False, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname=:name"),
            {"name": db_name},
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    admin_engine.dispose()


@pytest.fixture(scope="module", autouse=True)
def ensure_tables():
    """Recreate all tables before the E2E module runs, tear down after."""
    _ensure_database_exists(settings.POSTGRES_DB)
    engine = create_engine(settings.DATABASE_URL, echo=False)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)
    engine.dispose()
