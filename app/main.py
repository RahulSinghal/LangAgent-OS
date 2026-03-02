"""FastAPI application factory for LangGraph AgentOS."""

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.logging import setup_logging

# Route modules (register as each phase implements them)
from app.api.routes_health import router as health_router
from app.api.routes_projects import router as projects_router
from app.api.routes_sessions import router as sessions_router
from app.api.routes_runs import router as runs_router
from app.api.routes_approvals import router as approvals_router
from app.api.routes_artifacts import router as artifacts_router
from app.api.routes_traceability import router as traceability_router
from app.api.routes_documents import router as documents_router
from app.api.routes_sot import router as sot_router
from app.api.routes_system import router as system_router

# Phase 3 routers
from app.api.routes_auth import router as auth_router
from app.api.routes_policies import router as policies_router
from app.api.routes_governance import router as governance_router

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup / shutdown lifecycle hook."""
    setup_logging()
    # Ensure artifact storage directory exists
    os.makedirs(settings.ARTIFACTS_DIR, exist_ok=True)
    # Determine effective agent mode (real vs mock) based on key availability.
    try:
        from app.core.runtime import refresh_runtime_status
        refresh_runtime_status(validate_llm=True)
    except Exception:
        # Never block startup on LLM validation
        pass
    logger.info("AgentOS starting", version=settings.APP_VERSION, debug=settings.DEBUG)
    yield
    logger.info("AgentOS shutting down")


def create_app() -> FastAPI:
    """Build and return the FastAPI application."""
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "LangGraph AgentOS — a consulting delivery operating system. "
            "Supervisor agent dynamically assembles teams, executes task DAGs, "
            "and enforces approval gates for PRD and SOW artifacts."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # ── UI (no build step) ────────────────────────────────────────
    ui_dir = Path(__file__).parent / "ui"
    if ui_dir.exists():
        app.mount("/ui", StaticFiles(directory=str(ui_dir), html=True), name="ui")

        @app.get("/", include_in_schema=False)
        def _ui_index() -> FileResponse:
            return FileResponse(str(ui_dir / "index.html"))

    # ── CORS ─────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],   # Tighten in Phase 3 with org-scoped origins
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routers ──────────────────────────────────────────────────
    # Health — always active
    app.include_router(health_router)

    # Phase 1B+: project / session / run / approval / artifact routes
    app.include_router(projects_router, prefix=settings.API_PREFIX)
    app.include_router(sessions_router, prefix=settings.API_PREFIX)
    app.include_router(runs_router, prefix=settings.API_PREFIX)
    app.include_router(approvals_router, prefix=settings.API_PREFIX)
    app.include_router(artifacts_router, prefix=settings.API_PREFIX)
    app.include_router(documents_router, prefix=settings.API_PREFIX)
    app.include_router(sot_router, prefix=settings.API_PREFIX)
    app.include_router(system_router, prefix=settings.API_PREFIX)

    # Phase 2: traceability matrix routes
    app.include_router(traceability_router, prefix=settings.API_PREFIX)

    # Phase 3: auth + governance routes
    app.include_router(auth_router, prefix=settings.API_PREFIX)
    app.include_router(policies_router, prefix=settings.API_PREFIX)
    app.include_router(governance_router, prefix=settings.API_PREFIX)

    return app


app = create_app()
