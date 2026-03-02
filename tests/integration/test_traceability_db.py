"""Integration tests for Phase 2 - traceability service (requires DB)."""

import pytest
from sqlalchemy.orm import Session

from app.services.projects import create_project
from app.services.traceability import (
    create_trace_link,
    delete_trace_link,
    get_traceability_matrix,
    list_trace_links,
)


def test_create_trace_link(db: Session):
    project = create_project(db, name="Trace Project")
    link = create_trace_link(db, project.id, "r1", "TC-001")
    assert link.id is not None
    assert link.project_id == project.id
    assert link.requirement_id == "r1"
    assert link.test_id == "TC-001"
    assert link.link_type == "test"


def test_create_trace_link_with_custom_type(db: Session):
    project = create_project(db, name="Trace Type Project")
    link = create_trace_link(db, project.id, "r2", "US-42", link_type="backlog", notes="Sprint 3")
    assert link.link_type == "backlog"
    assert link.notes == "Sprint 3"


def test_list_trace_links_for_project(db: Session):
    project = create_project(db, name="List Trace Project")
    create_trace_link(db, project.id, "r1", "TC-001")
    create_trace_link(db, project.id, "r1", "TC-002")
    create_trace_link(db, project.id, "r2", "TC-003")

    links = list_trace_links(db, project.id)
    assert len(links) == 3


def test_list_trace_links_filtered_by_requirement(db: Session):
    project = create_project(db, name="Filter Trace Project")
    create_trace_link(db, project.id, "r1", "TC-001")
    create_trace_link(db, project.id, "r2", "TC-002")

    links = list_trace_links(db, project.id, requirement_id="r1")
    assert len(links) == 1
    assert links[0].requirement_id == "r1"


def test_list_trace_links_empty_for_other_project(db: Session):
    p1 = create_project(db, name="P1")
    p2 = create_project(db, name="P2")
    create_trace_link(db, p1.id, "r1", "TC-001")

    links = list_trace_links(db, p2.id)
    assert links == []


def test_delete_trace_link(db: Session):
    project = create_project(db, name="Delete Trace Project")
    link = create_trace_link(db, project.id, "r1", "TC-001")

    result = delete_trace_link(db, link.id)
    assert result is True

    remaining = list_trace_links(db, project.id)
    assert len(remaining) == 0


def test_delete_nonexistent_trace_link_returns_false(db: Session):
    result = delete_trace_link(db, 999999)
    assert result is False


def test_traceability_matrix_basic(db: Session):
    project = create_project(db, name="Matrix Project")
    create_trace_link(db, project.id, "r1", "TC-001")
    create_trace_link(db, project.id, "r1", "TC-002")
    create_trace_link(db, project.id, "r2", "TC-003")

    matrix = get_traceability_matrix(db, project.id)

    assert "r1" in matrix["matrix"]
    assert "r2" in matrix["matrix"]
    assert set(matrix["matrix"]["r1"]) == {"TC-001", "TC-002"}
    assert matrix["coverage"]["r1"] == 2
    assert matrix["coverage"]["r2"] == 1
    assert matrix["total_links"] == 3


def test_traceability_matrix_uncovered(db: Session):
    project = create_project(db, name="Coverage Gap Project")
    create_trace_link(db, project.id, "r1", "TC-001")

    # Pass all requirement IDs including uncovered ones
    matrix = get_traceability_matrix(db, project.id, requirement_ids=["r1", "r2", "r3"])

    assert "r2" in matrix["uncovered"]
    assert "r3" in matrix["uncovered"]
    assert "r1" not in matrix["uncovered"]


def test_traceability_matrix_coverage_stats(db: Session):
    project = create_project(db, name="Stats Project")
    create_trace_link(db, project.id, "r1", "TC-001")
    create_trace_link(db, project.id, "r2", "TC-002")

    matrix = get_traceability_matrix(
        db, project.id, requirement_ids=["r1", "r2", "r3"]
    )
    stats = matrix["summary_stats"]
    assert stats["total_requirements"] == 3
    assert stats["covered"] == 2
    assert stats["coverage_pct"] == pytest.approx(66.7, abs=0.1)


def test_traceability_matrix_empty_project(db: Session):
    project = create_project(db, name="Empty Project")
    matrix = get_traceability_matrix(db, project.id)
    assert matrix["total_links"] == 0
    assert matrix["matrix"] == {}
    assert matrix["summary_stats"]["coverage_pct"] == 0.0
