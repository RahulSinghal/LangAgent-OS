"""Traceability service — Phase 2.

Manages trace_links between SoT requirement IDs and test case IDs.
Exposes:
  create_trace_link   — add a new requirement ↔ test link
  delete_trace_link   — remove a link by id
  list_trace_links    — all links for a project
  get_traceability_matrix — full matrix with coverage stats
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import TraceLink


# ── CRUD ──────────────────────────────────────────────────────────────────────

def create_trace_link(
    db: Session,
    project_id: int,
    requirement_id: str,
    test_id: str,
    link_type: str = "test",
    milestone_id: str | None = None,
    eval_type: str | None = None,
    source: str = "manual",
    notes: str | None = None,
) -> TraceLink:
    """Create a trace_link record linking a requirement to a test case.

    Args:
        db:             Active DB session.
        project_id:     Project the link belongs to.
        requirement_id: SoT requirement ID (e.g. "r1").
        test_id:        Test case identifier (e.g. "TC-001").
        link_type:      "test" | "backlog" | "architecture" (default "test").
        milestone_id:   Optional MilestoneItem.id this link belongs to.
        eval_type:      "unit" | "integration" | "e2e" | "contract" | "manual".
        source:         "manual" | "auto" — how the link was created.
        notes:          Optional free-text notes.

    Returns:
        The created TraceLink ORM record.
    """
    link = TraceLink(
        project_id=project_id,
        requirement_id=requirement_id,
        test_id=test_id,
        link_type=link_type,
        milestone_id=milestone_id,
        eval_type=eval_type,
        source=source,
        notes=notes,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


def update_trace_link_status(
    db: Session,
    link_id: int,
    last_run_status: str | None,
) -> TraceLink | None:
    """Update the last_run_status of a trace link (pass/fail/skip/None).

    Returns:
        Updated TraceLink, or None if not found.
    """
    link = db.get(TraceLink, link_id)
    if link is None:
        return None
    link.last_run_status = last_run_status
    db.commit()
    db.refresh(link)
    return link


def delete_trace_link(db: Session, link_id: int) -> bool:
    """Delete a trace link by its DB id.

    Returns:
        True if deleted, False if not found.
    """
    link = db.get(TraceLink, link_id)
    if link is None:
        return False
    db.delete(link)
    db.commit()
    return True


def list_trace_links(
    db: Session,
    project_id: int,
    requirement_id: str | None = None,
) -> list[TraceLink]:
    """List all trace links for a project, optionally filtered by requirement.

    Args:
        db:             Active DB session.
        project_id:     Project to query.
        requirement_id: Optional filter — only links for this requirement.

    Returns:
        List of TraceLink records ordered by requirement_id, test_id.
    """
    q = (
        db.query(TraceLink)
        .filter(TraceLink.project_id == project_id)
    )
    if requirement_id is not None:
        q = q.filter(TraceLink.requirement_id == requirement_id)
    return q.order_by(TraceLink.requirement_id, TraceLink.test_id).all()


def get_traceability_matrix(
    db: Session,
    project_id: int,
    requirement_ids: list[str] | None = None,
) -> dict:
    """Build the full traceability matrix for a project.

    Returns a dict with:
      matrix:       { requirement_id: [test_id, ...], ... }
      coverage:     { requirement_id: <count of tests>, ... }
      uncovered:    [requirement_id, ...] — requirements with no tests
      total_links:  int
      summary_stats: { total_requirements: int, covered: int, coverage_pct: float }

    Args:
        db:               Active DB session.
        project_id:       Project to query.
        requirement_ids:  If provided, limits the matrix to these requirements.
                          Uncovered reqs are derived from this list.
    """
    links = list_trace_links(db, project_id)

    # Build matrix
    matrix: dict[str, list[str]] = {}
    for link in links:
        matrix.setdefault(link.requirement_id, [])
        if link.test_id not in matrix[link.requirement_id]:
            matrix[link.requirement_id].append(link.test_id)

    # Coverage counts
    coverage = {req_id: len(tests) for req_id, tests in matrix.items()}

    # Uncovered requirements
    if requirement_ids is not None:
        all_reqs = set(requirement_ids)
    else:
        all_reqs = set(matrix.keys())

    uncovered = sorted(r for r in all_reqs if coverage.get(r, 0) == 0)

    total_reqs = len(all_reqs)
    covered_count = sum(1 for r in all_reqs if coverage.get(r, 0) > 0)
    coverage_pct = round(covered_count / total_reqs * 100, 1) if total_reqs > 0 else 0.0

    return {
        "matrix": matrix,
        "coverage": coverage,
        "uncovered": uncovered,
        "total_links": len(links),
        "summary_stats": {
            "total_requirements": total_reqs,
            "covered": covered_count,
            "coverage_pct": coverage_pct,
        },
    }
