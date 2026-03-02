"""SQLAlchemy engine and session factory.

Phase 1A: engine + SessionLocal wired up, models not yet imported.
Phase 1B: Base.metadata.create_all replaced by Alembic migrations.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,       # detect dropped DB connections
    pool_size=5,
    max_overflow=10,
    echo=settings.DEBUG,      # log SQL in debug mode
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,   # avoid lazy-load surprises after commit
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency — yields a DB session and guarantees cleanup."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
