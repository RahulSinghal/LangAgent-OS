"""Integration test fixtures — requires a live PostgreSQL instance."""

import os

# Force integration tests onto an isolated DB to avoid clobbering dev/server DB.
os.environ.setdefault("POSTGRES_DB", "agentosdb_integration")

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

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
            conn.execute(text(f'CREATE DATABASE \"{db_name}\"'))
    admin_engine.dispose()


@pytest.fixture(scope="module")
def db() -> Session:
    """
    Creates a fresh test schema, yields a session, then tears down.
    Runs once per test module to keep the suite fast.
    """
    _ensure_database_exists(settings.POSTGRES_DB)
    engine = create_engine(settings.DATABASE_URL, echo=False)
    Base.metadata.drop_all(engine)   # clean slate
    Base.metadata.create_all(engine) # create all tables

    TestSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestSession()

    yield session

    session.close()
    Base.metadata.drop_all(engine)   # teardown
    engine.dispose()
