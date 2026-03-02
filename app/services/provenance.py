"""Provenance and observability service — Phase 3E.

Records provenance links, run metrics, and audit log events.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import AuditLog, ProvenanceLink, RunMetrics


# ── Provenance links ──────────────────────────────────────────────────────────

def record_provenance(
    db: Session,
    artifact_id: int,
    run_id: int,
    sot_fields: list[str],
    source_node: str,
) -> list[ProvenanceLink]:
    """Create one ProvenanceLink per SoT field.  Returns the created links."""
    links: list[ProvenanceLink] = []
    for field in sot_fields:
        link = ProvenanceLink(
            artifact_id=artifact_id,
            run_id=run_id,
            sot_field=field,
            source_node=source_node,
        )
        db.add(link)
        links.append(link)
    db.commit()
    for link in links:
        db.refresh(link)
    return links


def get_provenance(db: Session, artifact_id: int) -> list[ProvenanceLink]:
    """Return all provenance links for an artifact."""
    return (
        db.query(ProvenanceLink)
        .filter(ProvenanceLink.artifact_id == artifact_id)
        .order_by(ProvenanceLink.id)
        .all()
    )


# ── Run metrics ───────────────────────────────────────────────────────────────

def record_run_metrics(
    db: Session,
    run_id: int,
    project_id: int,
    total_tokens: int = 0,
    total_cost_usd: float = 0.0,
    total_latency_ms: int = 0,
    node_metrics: dict | None = None,
) -> RunMetrics:
    """Upsert run metrics for a given run.

    If a RunMetrics row already exists for *run_id*, update it in-place.
    """
    existing = db.query(RunMetrics).filter(RunMetrics.run_id == run_id).first()
    if existing is not None:
        existing.total_tokens = total_tokens
        existing.total_cost_usd = total_cost_usd
        existing.total_latency_ms = total_latency_ms
        existing.node_metrics_jsonb = node_metrics or {}
        db.commit()
        db.refresh(existing)
        return existing

    metrics = RunMetrics(
        run_id=run_id,
        project_id=project_id,
        total_tokens=total_tokens,
        total_cost_usd=total_cost_usd,
        total_latency_ms=total_latency_ms,
        node_metrics_jsonb=node_metrics or {},
    )
    db.add(metrics)
    db.commit()
    db.refresh(metrics)
    return metrics


def get_run_metrics(db: Session, run_id: int) -> RunMetrics | None:
    """Return run metrics for *run_id*, or None."""
    return db.query(RunMetrics).filter(RunMetrics.run_id == run_id).first()


# ── Audit log ─────────────────────────────────────────────────────────────────

def log_audit_event(
    db: Session,
    event_type: str,
    actor: str = "system",
    org_id: int | None = None,
    project_id: int | None = None,
    run_id: int | None = None,
    detail: dict | None = None,
) -> AuditLog:
    """Append an immutable audit log entry."""
    entry = AuditLog(
        event_type=event_type,
        actor=actor,
        org_id=org_id,
        project_id=project_id,
        run_id=run_id,
        detail_jsonb=detail or {},
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def get_audit_log(
    db: Session,
    project_id: int | None = None,
    run_id: int | None = None,
    org_id: int | None = None,
    limit: int = 100,
) -> list[AuditLog]:
    """Return audit log entries filtered by the supplied optional fields."""
    q = db.query(AuditLog)
    if project_id is not None:
        q = q.filter(AuditLog.project_id == project_id)
    if run_id is not None:
        q = q.filter(AuditLog.run_id == run_id)
    if org_id is not None:
        q = q.filter(AuditLog.org_id == org_id)
    return q.order_by(AuditLog.created_at.desc()).limit(limit).all()
