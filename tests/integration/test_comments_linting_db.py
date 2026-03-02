"""Integration tests for artifact comments and linting — Phase 3E.

Tests: add_comment, list_comments, resolve_comment, delete_comment,
       save_lint_report, get_lint_report.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.services.projects import create_project
from app.services.runs import create_run
from app.services.comments import (
    add_comment,
    delete_comment,
    list_comments,
    resolve_comment,
)
from app.services.linting import (
    get_lint_report,
    lint_artifact,
    save_lint_report,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_artifact(db, project_id: int, artifact_type: str = "prd"):
    from app.db.models import Artifact
    art = Artifact(project_id=project_id, type=artifact_type, version=1)
    db.add(art)
    db.commit()
    db.refresh(art)
    return art


# ── Artifact comments ─────────────────────────────────────────────────────────

def test_add_comment_basic(db: Session):
    project = create_project(db, name="Comment Project A")
    artifact = _make_artifact(db, project.id)
    comment = add_comment(
        db,
        artifact_id=artifact.id,
        project_id=project.id,
        author="reviewer@company.com",
        body="The problem statement is unclear.",
    )
    assert comment.id is not None
    assert comment.author == "reviewer@company.com"
    assert comment.body == "The problem statement is unclear."
    assert comment.resolved is False


def test_add_comment_with_section(db: Session):
    project = create_project(db, name="Comment Project B")
    artifact = _make_artifact(db, project.id)
    comment = add_comment(
        db,
        artifact_id=artifact.id,
        project_id=project.id,
        author="pm@company.com",
        body="Goals need to be SMART.",
        section="## Goals",
    )
    assert comment.section == "## Goals"


def test_list_comments_returns_all(db: Session):
    project = create_project(db, name="ListComment Project")
    artifact = _make_artifact(db, project.id)
    add_comment(db, artifact_id=artifact.id, project_id=project.id,
                author="a@test.com", body="Comment 1")
    add_comment(db, artifact_id=artifact.id, project_id=project.id,
                author="b@test.com", body="Comment 2")
    comments = list_comments(db, artifact_id=artifact.id)
    assert len(comments) >= 2


def test_list_comments_include_resolved(db: Session):
    project = create_project(db, name="ListCommentResolved Project")
    artifact = _make_artifact(db, project.id)
    c = add_comment(db, artifact_id=artifact.id, project_id=project.id,
                    author="x@test.com", body="Resolved comment")
    resolve_comment(db, c.id)
    # Default: include resolved
    all_comments = list_comments(db, artifact_id=artifact.id, include_resolved=True)
    ids = [cm.id for cm in all_comments]
    assert c.id in ids


def test_list_comments_exclude_resolved(db: Session):
    project = create_project(db, name="ExcludeResolved Project")
    artifact = _make_artifact(db, project.id)
    open_c = add_comment(db, artifact_id=artifact.id, project_id=project.id,
                         author="x@test.com", body="Open comment")
    resolved_c = add_comment(db, artifact_id=artifact.id, project_id=project.id,
                             author="y@test.com", body="Resolved comment")
    resolve_comment(db, resolved_c.id)
    # Exclude resolved
    open_comments = list_comments(db, artifact_id=artifact.id, include_resolved=False)
    ids = [cm.id for cm in open_comments]
    assert open_c.id in ids
    assert resolved_c.id not in ids


def test_resolve_comment(db: Session):
    project = create_project(db, name="ResolveComment Project")
    artifact = _make_artifact(db, project.id)
    comment = add_comment(db, artifact_id=artifact.id, project_id=project.id,
                          author="a@test.com", body="Fix this section please.")
    assert comment.resolved is False
    resolved = resolve_comment(db, comment.id)
    assert resolved.resolved is True


def test_resolve_nonexistent_comment_raises(db: Session):
    with pytest.raises(Exception):
        resolve_comment(db, comment_id=999999)


def test_delete_comment(db: Session):
    project = create_project(db, name="DeleteComment Project")
    artifact = _make_artifact(db, project.id)
    comment = add_comment(db, artifact_id=artifact.id, project_id=project.id,
                          author="del@test.com", body="Delete me.")
    result = delete_comment(db, comment.id)
    assert result is True
    remaining = list_comments(db, artifact_id=artifact.id)
    assert comment.id not in [c.id for c in remaining]


def test_delete_nonexistent_comment_returns_false(db: Session):
    result = delete_comment(db, comment_id=999999)
    assert result is False


def test_comments_scoped_to_artifact(db: Session):
    project = create_project(db, name="ScopedComment Project")
    art1 = _make_artifact(db, project.id, "prd")
    art2 = _make_artifact(db, project.id, "sow")
    add_comment(db, artifact_id=art1.id, project_id=project.id,
                author="a@test.com", body="PRD comment")
    add_comment(db, artifact_id=art2.id, project_id=project.id,
                author="b@test.com", body="SOW comment")
    art1_comments = list_comments(db, artifact_id=art1.id)
    bodies = [c.body for c in art1_comments]
    assert "PRD comment" in bodies
    assert "SOW comment" not in bodies


# ── Lint reports ──────────────────────────────────────────────────────────────

_GOOD_PRD = """# PRD

## Problem Statement
The system is slow and needs a full redesign for enterprise scalability requirements.

## Goals
- Improve performance by 40 percent
- Support 10,000 concurrent users without degradation

## Requirements
- [R-1] The system shall support 10k concurrent users
- [R-2] Response time shall be under 200ms at p99

## Success Metrics
Performance benchmarks met within 90 days of go-live deployment.
"""


def test_save_lint_report_passes(db: Session):
    project = create_project(db, name="LintReport Project Pass")
    artifact = _make_artifact(db, project.id)
    report = lint_artifact(_GOOD_PRD, "prd")
    lr = save_lint_report(db, artifact_id=artifact.id, run_id=None, report=report)
    assert lr.id is not None
    assert lr.passed == report["passed"]
    assert lr.artifact_id == artifact.id


def test_save_lint_report_failing(db: Session):
    project = create_project(db, name="LintReport Project Fail")
    artifact = _make_artifact(db, project.id)
    report = lint_artifact("Too short content.", "prd")
    lr = save_lint_report(db, artifact_id=artifact.id, run_id=None, report=report)
    assert lr.passed is False
    assert len(lr.findings_jsonb) > 0


def test_save_lint_report_with_run(db: Session):
    project = create_project(db, name="LintReport WithRun Project")
    run = create_run(db, project_id=project.id)
    artifact = _make_artifact(db, project.id)
    report = lint_artifact(_GOOD_PRD, "prd")
    lr = save_lint_report(db, artifact_id=artifact.id, run_id=run.id, report=report)
    assert lr.run_id == run.id


def test_get_lint_report_latest(db: Session):
    project = create_project(db, name="GetLintReport Project")
    artifact = _make_artifact(db, project.id)
    # Save two reports — second is newer
    r1 = lint_artifact("Short.", "prd")
    r2 = lint_artifact(_GOOD_PRD, "prd")
    save_lint_report(db, artifact_id=artifact.id, run_id=None, report=r1)
    save_lint_report(db, artifact_id=artifact.id, run_id=None, report=r2)
    # get_lint_report returns most recent
    fetched = get_lint_report(db, artifact_id=artifact.id)
    assert fetched is not None
    assert fetched.passed == r2["passed"]


def test_get_lint_report_not_found(db: Session):
    result = get_lint_report(db, artifact_id=999999)
    assert result is None


def test_lint_report_severity_counts_stored(db: Session):
    project = create_project(db, name="SeverityCounts Project")
    artifact = _make_artifact(db, project.id)
    report = lint_artifact("Short.", "prd")
    lr = save_lint_report(db, artifact_id=artifact.id, run_id=None, report=report)
    assert "error" in lr.severity_counts_jsonb
    assert lr.severity_counts_jsonb["error"] > 0
