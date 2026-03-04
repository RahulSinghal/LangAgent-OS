"""Eval report service.

Builds a structured report answering:
  "For every project and every milestone, what eval is used to test each feature?"

The report joins three data sources:
  1. SoT ProjectState  — milestones (coding_plan) and requirements
  2. TraceLink DB rows — manually-added requirement ↔ test mappings
  3. Test file scan    — auto-detected links by finding requirement IDs
                         (e.g. [R-001] or req_id refs) inside test files

Public API:
  build_eval_report(db, project_id, test_root) -> dict
  build_eval_report_md(report)                 -> str   (markdown)
  auto_detect_links(db, project_id, test_root) -> list[TraceLink]
"""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.models import Run, Snapshot, TraceLink
from app.services.traceability import create_trace_link, list_trace_links
from app.sot.state import ProjectState


# ── Helpers ───────────────────────────────────────────────────────────────────

# Patterns that identify a requirement reference inside a test file.
# Matches: [R-001], [r-1], R001, req_id="abc123", requirement_id: "abc123"
_REQ_PATTERNS: list[re.Pattern] = [
    re.compile(r"\[R-?(\w+)\]", re.IGNORECASE),
    re.compile(r"req(?:uirement)?[_\s-]?id[\"'\s:=]+([a-zA-Z0-9_-]+)", re.IGNORECASE),
]

# Maps test file path patterns to eval_type labels
_EVAL_TYPE_MAP: list[tuple[re.Pattern, str]] = [
    (re.compile(r"[/\\]unit[/\\]",        re.IGNORECASE), "unit"),
    (re.compile(r"[/\\]integration[/\\]", re.IGNORECASE), "integration"),
    (re.compile(r"[/\\]e2e[/\\]",         re.IGNORECASE), "e2e"),
    (re.compile(r"[/\\]contract[/\\]",    re.IGNORECASE), "contract"),
    (re.compile(r"test_e2e",              re.IGNORECASE), "e2e"),
    (re.compile(r"test_integration",      re.IGNORECASE), "integration"),
    (re.compile(r"test_unit",             re.IGNORECASE), "unit"),
]

_TEST_FILE_GLOBS = ["test_*.py", "*_test.py", "*.spec.ts", "*.test.ts", "*.spec.js"]


def _infer_eval_type(file_path: str) -> str:
    for pattern, label in _EVAL_TYPE_MAP:
        if pattern.search(file_path):
            return label
    return "unit"  # conservative default


def _extract_req_ids(content: str) -> set[str]:
    """Return all requirement IDs referenced in a block of text."""
    found: set[str] = set()
    for pattern in _REQ_PATTERNS:
        for match in pattern.finditer(content):
            found.add(match.group(1).lower())
    return found


def _load_latest_project_state(db: Session, project_id: int) -> ProjectState | None:
    """Load the most recent SoT snapshot for any run in this project."""
    row = (
        db.query(Snapshot)
        .join(Run, Run.id == Snapshot.run_id)
        .filter(Run.project_id == project_id)
        .order_by(Snapshot.id.desc())
        .first()
    )
    if row is None:
        return None
    return ProjectState(**row.state_jsonb)


# ── Auto-detection ────────────────────────────────────────────────────────────

def auto_detect_links(
    db: Session,
    project_id: int,
    test_root: str | Path,
) -> list[TraceLink]:
    """Scan *test_root* for test files and auto-create TraceLink rows.

    For each test file found:
      - Extracts requirement ID references via regex
      - Infers eval_type from the file path
      - Creates a TraceLink(source="auto") if one doesn't already exist

    Returns the list of newly created TraceLink records.
    """
    root = Path(test_root)
    if not root.exists():
        return []

    # Build a set of (requirement_id, test_id) pairs that already exist
    existing = {
        (lnk.requirement_id, lnk.test_id)
        for lnk in list_trace_links(db, project_id)
    }

    created: list[TraceLink] = []

    for glob_pattern in _TEST_FILE_GLOBS:
        for test_file in root.rglob(glob_pattern):
            try:
                content = test_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            req_ids = _extract_req_ids(content)
            if not req_ids:
                continue

            test_id = test_file.stem          # e.g. "test_auth_login"
            eval_type = _infer_eval_type(str(test_file))

            for req_id in req_ids:
                if (req_id, test_id) in existing:
                    continue
                link = create_trace_link(
                    db,
                    project_id=project_id,
                    requirement_id=req_id,
                    test_id=test_id,
                    eval_type=eval_type,
                    source="auto",
                    notes=str(test_file.relative_to(root)),
                )
                created.append(link)
                existing.add((req_id, test_id))

    return created


# ── Report builder ────────────────────────────────────────────────────────────

def build_eval_report(
    db: Session,
    project_id: int,
    test_root: str | Path | None = None,
) -> dict:
    """Build the full eval report for a project.

    Structure:
      project_id:   int
      milestones:   list of {
        milestone_id, name, description, status,
        features: list of {
          requirement_id, text, category, priority,
          evals: list of {
            test_id, eval_type, source, link_type, notes
          },
          covered: bool
        },
        coverage: { total, covered, pct }
      }
      ungrouped_features: list — requirements not in any milestone
      summary: { total_milestones, total_features, covered_features, coverage_pct }

    Args:
        db:         Active DB session.
        project_id: Project to report on.
        test_root:  If provided, auto-detect links from test files before building.
    """
    # Optionally auto-detect links first
    if test_root is not None:
        auto_detect_links(db, project_id, test_root)

    # Load SoT
    sot = _load_latest_project_state(db, project_id)

    # Load all trace links
    all_links = list_trace_links(db, project_id)

    # Index links by requirement_id for fast lookup
    links_by_req: dict[str, list[TraceLink]] = {}
    for lnk in all_links:
        links_by_req.setdefault(lnk.requirement_id, []).append(lnk)

    # Index links by milestone_id for milestone-scoped links
    links_by_milestone: dict[str, list[TraceLink]] = {}
    for lnk in all_links:
        if lnk.milestone_id:
            links_by_milestone.setdefault(lnk.milestone_id, []).append(lnk)

    # Build requirement lookup from SoT (id → RequirementItem)
    req_by_id: dict[str, dict] = {}
    if sot:
        for req in sot.requirements:
            req_by_id[req.id] = req.model_dump()

    # Track which requirement_ids are covered by milestones
    milestone_covered_req_ids: set[str] = set()

    milestones_out: list[dict] = []

    if sot and sot.coding_plan:
        for milestone in sot.coding_plan:
            mid = milestone.id

            # Collect features: all stories referenced by this milestone
            # Stories are backlog refs; we map them to requirements by ID or text match
            feature_req_ids: list[str] = _resolve_stories_to_req_ids(
                milestone.stories, req_by_id
            )

            features_out: list[dict] = []
            for req_id in feature_req_ids:
                req_info = req_by_id.get(req_id, {"id": req_id, "text": req_id})

                # Collect evals: milestone-scoped links first, then req-level links
                evals = _collect_evals(req_id, mid, links_by_req, links_by_milestone)

                features_out.append({
                    "requirement_id": req_id,
                    "text": req_info.get("text", ""),
                    "category": req_info.get("category", ""),
                    "priority": req_info.get("priority", ""),
                    "evals": evals,
                    "covered": len(evals) > 0,
                })
                milestone_covered_req_ids.add(req_id)

            covered_count = sum(1 for f in features_out if f["covered"])
            total_count = len(features_out)

            milestones_out.append({
                "milestone_id": mid,
                "name": milestone.name,
                "description": milestone.description,
                "status": milestone.status,
                "features": features_out,
                "coverage": {
                    "total": total_count,
                    "covered": covered_count,
                    "pct": round(covered_count / total_count * 100, 1) if total_count else 0.0,
                },
            })

    # Ungrouped features — requirements not referenced by any milestone
    ungrouped: list[dict] = []
    for req_id, req_info in req_by_id.items():
        if req_id in milestone_covered_req_ids:
            continue
        evals = _collect_evals(req_id, None, links_by_req, links_by_milestone)
        ungrouped.append({
            "requirement_id": req_id,
            "text": req_info.get("text", ""),
            "category": req_info.get("category", ""),
            "priority": req_info.get("priority", ""),
            "evals": evals,
            "covered": len(evals) > 0,
        })

    total_features = sum(m["coverage"]["total"] for m in milestones_out) + len(ungrouped)
    covered_features = (
        sum(m["coverage"]["covered"] for m in milestones_out)
        + sum(1 for f in ungrouped if f["covered"])
    )

    return {
        "project_id": project_id,
        "milestones": milestones_out,
        "ungrouped_features": ungrouped,
        "summary": {
            "total_milestones": len(milestones_out),
            "total_features": total_features,
            "covered_features": covered_features,
            "coverage_pct": (
                round(covered_features / total_features * 100, 1) if total_features else 0.0
            ),
        },
    }


# ── Markdown renderer ─────────────────────────────────────────────────────────

def build_eval_report_md(report: dict) -> str:
    """Render the eval report dict as a human-readable markdown string."""
    lines: list[str] = [
        "# Eval Coverage Report",
        "",
        f"**Project ID:** {report['project_id']}",
        "",
    ]

    summary = report["summary"]
    lines += [
        "## Summary",
        "",
        f"| Milestones | Features | Covered | Coverage |",
        f"|---|---|---|---|",
        (
            f"| {summary['total_milestones']} "
            f"| {summary['total_features']} "
            f"| {summary['covered_features']} "
            f"| {summary['coverage_pct']}% |"
        ),
        "",
    ]

    for ms in report["milestones"]:
        cov = ms["coverage"]
        lines += [
            f"## Milestone: {ms['name']}",
            "",
            f"**ID:** `{ms['milestone_id']}` | "
            f"**Status:** {ms['status']} | "
            f"**Coverage:** {cov['covered']}/{cov['total']} ({cov['pct']}%)",
            "",
            f"_{ms['description']}_",
            "",
        ]

        if not ms["features"]:
            lines += ["_No features linked to this milestone._", ""]
            continue

        lines += [
            "| Feature | Category | Priority | Evals | Covered |",
            "|---|---|---|---|---|",
        ]
        for feat in ms["features"]:
            eval_summary = ", ".join(
                f"{e['test_id']} ({e['eval_type'] or 'unknown'})"
                for e in feat["evals"]
            ) or "—"
            covered_mark = "✓" if feat["covered"] else "✗"
            req_id = feat["requirement_id"]
            text = feat["text"][:60] + "…" if len(feat["text"]) > 60 else feat["text"]
            lines.append(
                f"| [{req_id}] {text} "
                f"| {feat['category']} "
                f"| {feat['priority']} "
                f"| {eval_summary} "
                f"| {covered_mark} |"
            )
        lines.append("")

    if report["ungrouped_features"]:
        lines += [
            "## Ungrouped Features (no milestone)",
            "",
            "| Feature | Category | Priority | Evals | Covered |",
            "|---|---|---|---|---|",
        ]
        for feat in report["ungrouped_features"]:
            eval_summary = ", ".join(
                f"{e['test_id']} ({e['eval_type'] or 'unknown'})"
                for e in feat["evals"]
            ) or "—"
            covered_mark = "✓" if feat["covered"] else "✗"
            req_id = feat["requirement_id"]
            text = feat["text"][:60] + "…" if len(feat["text"]) > 60 else feat["text"]
            lines.append(
                f"| [{req_id}] {text} "
                f"| {feat['category']} "
                f"| {feat['priority']} "
                f"| {eval_summary} "
                f"| {covered_mark} |"
            )
        lines.append("")

    return "\n".join(lines)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _resolve_stories_to_req_ids(
    stories: list[str],
    req_by_id: dict[str, dict],
) -> list[str]:
    """Map backlog story refs to requirement IDs.

    Strategy:
      1. If the story string is a direct requirement ID — use it.
      2. If the story matches a requirement's text (case-insensitive substring) — use it.
      3. Otherwise include the raw story ref as a synthetic requirement ID.
    """
    result: list[str] = []
    seen: set[str] = set()

    for story in stories:
        story_lower = story.lower().strip()

        # Direct ID match
        if story_lower in req_by_id:
            if story_lower not in seen:
                result.append(story_lower)
                seen.add(story_lower)
            continue

        # Text substring match
        matched = False
        for req_id, req_info in req_by_id.items():
            if story_lower in req_info.get("text", "").lower():
                if req_id not in seen:
                    result.append(req_id)
                    seen.add(req_id)
                matched = True
                break

        if not matched and story not in seen:
            result.append(story)
            seen.add(story)

    return result


def _collect_evals(
    req_id: str,
    milestone_id: str | None,
    links_by_req: dict[str, list[TraceLink]],
    links_by_milestone: dict[str, list[TraceLink]],
) -> list[dict]:
    """Collect all eval entries for a requirement, de-duplicated."""
    seen_test_ids: set[str] = set()
    evals: list[dict] = []

    # Milestone-scoped links first (more specific)
    if milestone_id:
        for lnk in links_by_milestone.get(milestone_id, []):
            if lnk.requirement_id == req_id and lnk.test_id not in seen_test_ids:
                evals.append(_link_to_eval_dict(lnk))
                seen_test_ids.add(lnk.test_id)

    # Requirement-level links (not milestone-scoped)
    for lnk in links_by_req.get(req_id, []):
        if lnk.test_id not in seen_test_ids:
            evals.append(_link_to_eval_dict(lnk))
            seen_test_ids.add(lnk.test_id)

    return evals


def _link_to_eval_dict(lnk: TraceLink) -> dict:
    return {
        "test_id": lnk.test_id,
        "eval_type": lnk.eval_type,
        "source": lnk.source,
        "link_type": lnk.link_type,
        "notes": lnk.notes,
    }
