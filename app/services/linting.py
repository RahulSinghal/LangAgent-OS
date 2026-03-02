"""Artifact linting engine -- Phase 3E.

Rules: MISSING_SECTION, EMPTY_SECTION, TOO_SHORT, REQUIREMENT_WITHOUT_ID.
"""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.db.models import ArtifactLintReport

nl = chr(10)

REQUIRED_SECTIONS_PRD: list[str] = ["## Problem Statement", "## Goals", "## Requirements", "## Success Metrics"]
REQUIRED_SECTIONS_SOW: list[str] = ["## Scope", "## Deliverables", "## Timeline", "## Commercials"]

_WORD_COUNT_THRESHOLD = 50

_PLACEHOLDER_PATTERNS: list[str] = [
    r"^\s*\[.*?\]\s*$",
    r"^\s*TODO",
    r"^\s*TBD",
    r"^\s*\.\.\.\s*$",
    r"^\s*N/?A\s*$",
]

_REQUIREMENT_ID_PATTERN = re.compile(r"\[R-\d+\]")


def _has_section(content: str, heading: str) -> bool:
    for line in content.splitlines():
        if line.strip().lower() == heading.strip().lower():
            return True
    return False


def _section_body(content: str, heading: str) -> str:
    in_section = False
    body_lines: list[str] = []
    for line in content.splitlines():
        if line.strip().lower() == heading.strip().lower():
            in_section = True
            continue
        if in_section:
            if re.match(r"^#{1,6}\s", line):
                break
            body_lines.append(line)
    return nl.join(body_lines).strip()


def _is_placeholder_body(body: str) -> bool:
    if not body:
        return True
    for pattern in _PLACEHOLDER_PATTERNS:
        if re.match(pattern, body, re.IGNORECASE | re.MULTILINE):
            return True
    return False


def _count_words(text: str) -> int:
    return len(text.split())


def _requirement_bullets(content: str) -> list[str]:
    body = _section_body(content, "## Requirements")
    return [ln.strip() for ln in body.splitlines() if ln.strip().startswith(("-", "*"))]


def lint_artifact(content: str, artifact_type: str) -> dict:
    """Lint artifact content. Returns lint report dict."""
    findings: list[dict] = []
    artifact_type_lower = artifact_type.lower()
    if artifact_type_lower == "prd":
        required_sections = REQUIRED_SECTIONS_PRD
    elif artifact_type_lower == "sow":
        required_sections = REQUIRED_SECTIONS_SOW
    else:
        required_sections = []

    for section in required_sections:
        if not _has_section(content, section):
            findings.append({"rule": "MISSING_SECTION", "message": f"Required section {section!r} is missing.", "severity": "error", "section": section})
        else:
            body = _section_body(content, section)
            if _is_placeholder_body(body):
                findings.append({"rule": "EMPTY_SECTION", "message": f"Section {section!r} is placeholder.", "severity": "warning", "section": section})

    word_count = _count_words(content)
    if word_count < _WORD_COUNT_THRESHOLD:
        findings.append({"rule": "TOO_SHORT", "message": f"Artifact has {word_count} words; min is {_WORD_COUNT_THRESHOLD}.", "severity": "error", "section": ""})

    if artifact_type_lower == "prd" and _has_section(content, "## Requirements"):
        for bullet in _requirement_bullets(content):
            if not _REQUIREMENT_ID_PATTERN.search(bullet):
                findings.append({"rule": "REQUIREMENT_WITHOUT_ID", "message": f"Bullet lacks [R-N] id: {bullet[:80]!r}", "severity": "warning", "section": "## Requirements"})

    severity_counts = {"error": 0, "warning": 0, "info": 0}
    for f in findings:
        sev = f.get("severity", "info")
        if sev in severity_counts:
            severity_counts[sev] += 1

    return {"findings": findings, "severity_counts": severity_counts, "passed": severity_counts["error"] == 0, "word_count": word_count}


def save_lint_report(db: Session, artifact_id: int, run_id: int | None, report: dict) -> ArtifactLintReport:
    """Persist a lint report to the database."""
    lr = ArtifactLintReport(artifact_id=artifact_id, run_id=run_id,
        findings_jsonb=report.get("findings", []),
        severity_counts_jsonb=report.get("severity_counts", {}),
        passed=report.get("passed", True))
    db.add(lr)
    db.commit()
    db.refresh(lr)
    return lr


def get_lint_report(db: Session, artifact_id: int) -> ArtifactLintReport | None:
    """Return the most recent lint report for an artifact, or None."""
    return (db.query(ArtifactLintReport).filter(ArtifactLintReport.artifact_id == artifact_id)
        .order_by(ArtifactLintReport.created_at.desc()).first())

