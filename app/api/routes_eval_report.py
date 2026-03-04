"""Eval report API routes.

Endpoints:
  GET  /projects/{project_id}/eval-report         — full eval report (JSON)
  POST /projects/{project_id}/eval-report/scan    — trigger auto-detection from test files
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.eval_report import auto_detect_links, build_eval_report, build_eval_report_md

router = APIRouter(tags=["eval-report"])

DbDep = Annotated[Session, Depends(get_db)]


@router.get(
    "/projects/{project_id}/eval-report",
    summary="Get eval coverage report for a project",
    response_model=None,
)
def get_eval_report(
    project_id: int,
    db: DbDep,
    test_root: str | None = Query(
        default=None,
        description=(
            "Absolute path to the test directory. "
            "If provided, auto-detection runs before the report is built."
        ),
    ),
    format: str = Query(
        default="json",
        description="Response format: 'json' or 'markdown'",
    ),
):
    """Return the eval coverage report for the project.

    The report shows, per milestone and per feature, which evals/tests are
    linked — and which features have no eval coverage at all.

    Query params:
      test_root  — if set, scan test files for requirement references first
      format     — 'json' (default) or 'markdown'
    """
    report = build_eval_report(db, project_id, test_root=test_root)

    if format == "markdown":
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(build_eval_report_md(report), media_type="text/markdown")

    return report


@router.post(
    "/projects/{project_id}/eval-report/scan",
    summary="Auto-detect eval links from test files",
)
def scan_test_files(
    project_id: int,
    db: DbDep,
    test_root: str = Query(
        description="Absolute path to the test directory to scan."
    ),
):
    """Scan *test_root* for test files and auto-create trace links.

    Finds requirement ID references (e.g. [R-001]) inside test files and
    creates TraceLink rows with source='auto'. Already-existing links are
    skipped. Returns the count of newly created links.
    """
    created = auto_detect_links(db, project_id, test_root)
    return {"created": len(created), "links": [lnk.id for lnk in created]}
