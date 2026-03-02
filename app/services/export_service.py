"""Export service — Phase 3G.

Produces a ZIP archive with:
  - PRD artifact (markdown)
  - SOW artifact (markdown)
  - Traceability matrix (CSV)
  - Change log (markdown listing all change requests)
  - Run metrics (JSON)
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.models import Artifact, ChangeRequest, RunMetrics
from app.services.change_control import list_change_requests
from app.services.provenance import get_provenance, get_run_metrics


# ── CSV / markdown builders ───────────────────────────────────────────────────

def build_traceability_csv(trace_links: list) -> str:
    """Return a CSV string from a list of ProvenanceLink (or TraceLink) objects.

    Columns: artifact_id, sot_field, source_node, run_id
    """
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["artifact_id", "sot_field", "source_node", "run_id"])
    for link in trace_links:
        # Support both ProvenanceLink and duck-typed objects
        artifact_id = getattr(link, "artifact_id", "")
        sot_field = getattr(link, "sot_field", getattr(link, "requirement_id", ""))
        source_node = getattr(link, "source_node", getattr(link, "test_id", ""))
        run_id = getattr(link, "run_id", "")
        writer.writerow([artifact_id, sot_field, source_node, run_id])
    return output.getvalue()


def build_change_log_md(change_requests: list) -> str:
    """Return a markdown change log from a list of ChangeRequest objects."""
    lines: list[str] = ["# Change Log", ""]
    if not change_requests:
        lines.append("_No change requests recorded._")
        return "\n".join(lines)

    for cr in change_requests:
        cr_id = getattr(cr, "id", "?")
        status = getattr(cr, "status", "unknown")
        requested_by = getattr(cr, "requested_by", None) or "system"
        reviewed_by = getattr(cr, "reviewed_by", None) or "—"
        created_at = getattr(cr, "created_at", None)
        resolved_at = getattr(cr, "resolved_at", None)
        review_notes = getattr(cr, "review_notes", None) or ""
        diff_jsonb = getattr(cr, "diff_jsonb", {}) or {}
        total_changes = diff_jsonb.get("total_changes", 0)

        lines.append(f"## CR-{cr_id}: {status.upper()}")
        lines.append("")
        lines.append(f"- **Requested by:** {requested_by}")
        lines.append(f"- **Created:** {created_at.isoformat() if created_at else 'unknown'}")
        lines.append(f"- **Status:** {status}")
        lines.append(f"- **Reviewed by:** {reviewed_by}")
        lines.append(
            f"- **Resolved:** {resolved_at.isoformat() if resolved_at else 'pending'}"
        )
        lines.append(f"- **Total field changes:** {total_changes}")
        if review_notes:
            lines.append(f"- **Notes:** {review_notes}")
        lines.append("")

    return "\n".join(lines)


# ── ZIP builder ───────────────────────────────────────────────────────────────

def build_export_zip(db: Session, project_id: int) -> bytes:
    """Build and return ZIP bytes for the project delivery pack.

    Reads artifacts from DB (types: 'prd', 'sow').
    Builds traceability CSV from provenance links.
    Builds change log markdown from all change requests.
    Includes run metrics JSON for the most recent run with metrics.
    Raises ValueError if no artifacts are found.
    """
    # Fetch artifacts for this project
    artifacts = (
        db.query(Artifact)
        .filter(Artifact.project_id == project_id)
        .order_by(Artifact.created_at.desc())
        .all()
    )
    if not artifacts:
        raise ValueError(f"No artifacts found for project {project_id}")

    # Group by type — take latest version of each type
    prd_artifact: Artifact | None = None
    sow_artifact: Artifact | None = None
    for artifact in artifacts:
        if artifact.type == "prd" and prd_artifact is None:
            prd_artifact = artifact
        elif artifact.type == "sow" and sow_artifact is None:
            sow_artifact = artifact

    # Collect all provenance links across artifacts
    all_trace_links: list = []
    for artifact in artifacts:
        links = get_provenance(db, artifact_id=artifact.id)
        all_trace_links.extend(links)

    # Fetch change requests
    crs: list[ChangeRequest] = list_change_requests(db, project_id=project_id)

    # Fetch metrics (latest run that has metrics for this project)
    metrics_obj: RunMetrics | None = (
        db.query(RunMetrics)
        .filter(RunMetrics.project_id == project_id)
        .order_by(RunMetrics.created_at.desc())
        .first()
    )

    # Build zip
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:

        # PRD artifact
        if prd_artifact is not None:
            prd_content = _read_artifact_content(prd_artifact)
            zf.writestr(f"prd_v{prd_artifact.version}.md", prd_content)
        else:
            zf.writestr("prd_missing.json", json.dumps({"note": "No PRD artifact found"}))

        # SOW artifact
        if sow_artifact is not None:
            sow_content = _read_artifact_content(sow_artifact)
            zf.writestr(f"sow_v{sow_artifact.version}.md", sow_content)
        else:
            zf.writestr("sow_missing.json", json.dumps({"note": "No SOW artifact found"}))

        # Traceability CSV
        trace_csv = build_traceability_csv(all_trace_links)
        zf.writestr("traceability_matrix.csv", trace_csv)

        # Change log markdown
        change_log_md = build_change_log_md(crs)
        zf.writestr("change_log.md", change_log_md)

        # Run metrics JSON
        if metrics_obj is not None:
            metrics_dict = {
                "run_id": metrics_obj.run_id,
                "project_id": metrics_obj.project_id,
                "total_tokens": metrics_obj.total_tokens,
                "total_cost_usd": metrics_obj.total_cost_usd,
                "total_latency_ms": metrics_obj.total_latency_ms,
                "node_metrics": metrics_obj.node_metrics_jsonb,
                "created_at": (
                    metrics_obj.created_at.isoformat() if metrics_obj.created_at else None
                ),
            }
        else:
            metrics_dict = {"note": "No run metrics found for this project"}
        zf.writestr("run_metrics.json", json.dumps(metrics_dict, indent=2))

    return zip_buffer.getvalue()


# ── Internal helper ───────────────────────────────────────────────────────────

def _read_artifact_content(artifact: Artifact) -> str:
    """Read artifact file from disk, or fall back to JSON metadata."""
    if artifact.file_path:
        path = Path(artifact.file_path)
        if path.exists():
            try:
                return path.read_text(encoding="utf-8")
            except OSError:
                pass

    # Fallback — include metadata as JSON
    return json.dumps(
        {
            "id": artifact.id,
            "type": artifact.type,
            "version": artifact.version,
            "file_path": artifact.file_path,
            "project_id": artifact.project_id,
            "note": "Artifact file not found on disk; metadata included instead.",
        },
        indent=2,
    )
