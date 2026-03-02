"""Unit tests for the artifact linting engine — Phase 3E.

Tests: lint_artifact for PRD and SOW artifacts, all four rules.
"""

from __future__ import annotations

import pytest

from app.services.linting import (
    REQUIRED_SECTIONS_PRD,
    REQUIRED_SECTIONS_SOW,
    lint_artifact,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _prd_with_all_sections(extra_content: str = "") -> str:
    """Generate a minimal valid PRD with all required sections."""
    return f"""# Product Requirements Document

## Problem Statement
The current workflow is inefficient and causes delays in project delivery for enterprise clients.

## Goals
- Reduce time-to-delivery by 30 percent
- Automate repetitive approval steps
- Improve visibility for stakeholders

## Requirements
- [R-1] The system shall support multi-tenant project isolation
- [R-2] The system shall provide a REST API for all major operations
- [R-3] The system shall generate PRD artifacts automatically

## Success Metrics
- Delivery time reduced by 30 percent within 6 months
- 95 percent of PRDs approved on first review
- System uptime of 99.9 percent
{extra_content}
"""


def _sow_with_all_sections() -> str:
    return """# Statement of Work

## Scope
This engagement covers the design, implementation, and testing of the AgentOS platform.

## Deliverables
- AgentOS platform version 1.0
- Technical documentation and runbooks
- Training sessions for operations team

## Timeline
Phase 1: 4 weeks — Discovery and architecture
Phase 2: 8 weeks — Core implementation
Phase 3: 4 weeks — Testing and deployment

## Commercials
Fixed fee of $150,000 USD payable in three milestone instalments.
"""


# ── PRD linting — all sections present ───────────────────────────────────────

def test_prd_all_sections_passes():
    report = lint_artifact(_prd_with_all_sections(), "prd")
    assert report["passed"] is True


def test_prd_report_has_required_keys():
    report = lint_artifact(_prd_with_all_sections(), "prd")
    assert "findings" in report
    assert "severity_counts" in report
    assert "passed" in report
    assert "word_count" in report


def test_prd_word_count_counted():
    content = _prd_with_all_sections()
    report = lint_artifact(content, "prd")
    assert report["word_count"] > 0


def test_prd_severity_counts_shape():
    report = lint_artifact(_prd_with_all_sections(), "prd")
    sc = report["severity_counts"]
    assert "error" in sc
    assert "warning" in sc
    assert "info" in sc


# ── PRD linting — MISSING_SECTION ────────────────────────────────────────────

def test_prd_missing_problem_statement():
    content = """# PRD

## Goals
Goal A, Goal B, Goal C, Goal D, Goal E, Goal F, Goal G, Goal H, Goal I, Goal J.

## Requirements
- [R-1] First requirement text for the system
- [R-2] Second requirement description goes here

## Success Metrics
Metric A: response time under 200ms for all API calls in production.
"""
    report = lint_artifact(content, "prd")
    rules = [f["rule"] for f in report["findings"]]
    assert "MISSING_SECTION" in rules


def test_prd_missing_goals():
    content = """# PRD

## Problem Statement
The problem is that existing solutions are slow and expensive for enterprise clients.

## Requirements
- [R-1] The system must be fast and responsive for end users

## Success Metrics
Response time under 200ms for all operations.
"""
    report = lint_artifact(content, "prd")
    rules = [f["rule"] for f in report["findings"]]
    assert "MISSING_SECTION" in rules


def test_prd_all_sections_missing():
    content = "# Some document\n\nJust a title."
    report = lint_artifact(content, "prd")
    missing = [f for f in report["findings"] if f["rule"] == "MISSING_SECTION"]
    assert len(missing) == len(REQUIRED_SECTIONS_PRD)
    assert report["passed"] is False


# ── PRD linting — TOO_SHORT ───────────────────────────────────────────────────

def test_prd_too_short():
    content = "## Problem Statement\nShort."
    report = lint_artifact(content, "prd")
    rules = [f["rule"] for f in report["findings"]]
    assert "TOO_SHORT" in rules
    assert report["passed"] is False


def test_prd_long_enough_no_too_short():
    content = _prd_with_all_sections()
    report = lint_artifact(content, "prd")
    rules = [f["rule"] for f in report["findings"]]
    assert "TOO_SHORT" not in rules


# ── PRD linting — REQUIREMENT_WITHOUT_ID ─────────────────────────────────────

def test_prd_requirement_without_id_flagged():
    content = """# PRD

## Problem Statement
The system is slow and costs too much for enterprise clients today.

## Goals
- Reduce cost by 50 percent
- Improve developer experience significantly

## Requirements
- This requirement has no ID tag at all

## Success Metrics
90 percent of users rate satisfaction as good or excellent.
"""
    report = lint_artifact(content, "prd")
    rules = [f["rule"] for f in report["findings"]]
    assert "REQUIREMENT_WITHOUT_ID" in rules


def test_prd_requirement_with_id_not_flagged():
    content = _prd_with_all_sections()
    report = lint_artifact(content, "prd")
    rules = [f["rule"] for f in report["findings"]]
    assert "REQUIREMENT_WITHOUT_ID" not in rules


# ── SOW linting ───────────────────────────────────────────────────────────────

def test_sow_all_sections_passes():
    report = lint_artifact(_sow_with_all_sections(), "sow")
    assert report["passed"] is True


def test_sow_missing_scope():
    content = """# SOW

## Deliverables
Deliverable A, B, C for the enterprise project implementation.

## Timeline
12 weeks total across three phases of development.

## Commercials
Fixed fee engagement with milestone-based payment schedule.
"""
    report = lint_artifact(content, "sow")
    rules = [f["rule"] for f in report["findings"]]
    assert "MISSING_SECTION" in rules


def test_sow_missing_all_sections():
    content = "# Statement of Work\n\nContent coming soon."
    report = lint_artifact(content, "sow")
    missing = [f for f in report["findings"] if f["rule"] == "MISSING_SECTION"]
    assert len(missing) == len(REQUIRED_SECTIONS_SOW)


# ── Unknown artifact type ─────────────────────────────────────────────────────

def test_unknown_artifact_type_no_section_rules():
    content = "Some content with enough words " * 10
    report = lint_artifact(content, "unknown_type")
    # No MISSING_SECTION rules should fire for unknown types
    rules = [f["rule"] for f in report["findings"]]
    assert "MISSING_SECTION" not in rules


def test_unknown_type_still_checks_word_count():
    report = lint_artifact("Too short.", "other")
    rules = [f["rule"] for f in report["findings"]]
    assert "TOO_SHORT" in rules


# ── EMPTY_SECTION ─────────────────────────────────────────────────────────────

def test_prd_placeholder_section_flagged():
    # Content is long enough (>50 words) to avoid TOO_SHORT, but has TODO in Problem Statement
    content = """# PRD — Enterprise Platform Requirements Document

## Problem Statement
TODO

## Goals
- Reduce operational costs by 40 percent over the next fiscal year
- Improve developer productivity through automation and better tooling
- Support 10,000 concurrent users with sub-200ms response times at p99
- Enable real-time analytics dashboards for all enterprise accounts globally

## Requirements
- [R-1] The system shall support multi-tenant project isolation at the org level
- [R-2] The system shall provide a comprehensive REST API for all operations
- [R-3] Automated PRD and SOW generation with configurable Jinja2 templates

## Success Metrics
- 30 percent reduction in time-to-delivery for enterprise consulting projects
- 95 percent of generated PRDs pass quality gate on first review attempt
- System uptime of 99.9 percent measured over rolling 30-day windows
"""
    report = lint_artifact(content, "prd")
    rules = [f["rule"] for f in report["findings"]]
    assert "EMPTY_SECTION" in rules


# ── severity counts accurate ──────────────────────────────────────────────────

def test_severity_counts_match_findings():
    content = "Short."   # triggers TOO_SHORT (error) + all MISSING_SECTION (errors)
    report = lint_artifact(content, "prd")
    error_count = sum(1 for f in report["findings"] if f["severity"] == "error")
    assert report["severity_counts"]["error"] == error_count


def test_passed_false_when_errors_present():
    report = lint_artifact("tiny", "prd")
    assert report["passed"] is False
    assert report["severity_counts"]["error"] > 0
