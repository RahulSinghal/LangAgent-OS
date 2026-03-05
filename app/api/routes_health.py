"""Health check endpoints — verifies the API, DB, and LLM connection are alive."""

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


class LLMHealthResponse(BaseModel):
    status: str          # "ok" | "error"
    provider: str
    model: str
    error: str | None = None


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


@router.get("/health/llm", response_model=LLMHealthResponse, summary="LLM provider health check")
def llm_health(settings: Settings = Depends(get_settings)) -> LLMHealthResponse:
    """Pings the configured LLM provider with a minimal prompt to verify credentials.

    This endpoint performs a real (low-cost) LLM call, so it may take a few
    seconds.  Use it to confirm that the API key and model are correctly
    configured before starting a run.
    """
    from app.services.llm_service import llm_healthcheck

    ok, error = llm_healthcheck()
    return LLMHealthResponse(
        status="ok" if ok else "error",
        provider=settings.LLM_PROVIDER,
        model=settings.LLM_MODEL,
        error=error,
    )
