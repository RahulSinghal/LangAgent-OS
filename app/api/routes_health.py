"""Health check endpoint — verifies the API and DB connection are alive."""

import time

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db

router = APIRouter(tags=["health"])

_start_time = time.time()


class HealthResponse(BaseModel):
    status: str
    version: str
    uptime_seconds: float
    database: str


@router.get("/health", response_model=HealthResponse, summary="Health check")
def health(
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> HealthResponse:
    """Returns API status, version, uptime, and DB connectivity."""
    try:
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as exc:
        db_status = f"error: {exc}"

    return HealthResponse(
        status="ok",
        version=settings.APP_VERSION,
        uptime_seconds=round(time.time() - _start_time, 2),
        database=db_status,
    )
