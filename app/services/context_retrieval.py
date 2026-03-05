"""Cross-project context retrieval service.

Provides:

1. store_component() / bulk_store_components()
   Save reusable patterns, templates, and decisions to ComponentStore.
   Deduplication: identical content (same component_type + SHA-256 hash)
   is silently skipped — storing the same requirement from 10 projects
   produces one row, not ten.

2. retrieve_relevant()
   Tag-overlap + recency-weighted scoring.  Excludes the requesting
   project's own components so intake never sees circular self-references.

3. auto_extract_and_store()
   Called by end_node on completion.  Always purges first — even when the
   revised SoT is empty — so stale v1 data never survives a v2 revision.

4. purge_auto_components()
   Delete all source='auto' rows for a project (preserves 'manual' ones).

Tag-based retrieval works without ML infrastructure.  Embedding/semantic
retrieval can be added later via an embedding column + cosine-similarity.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import ComponentStore


# ── Stop-words ────────────────────────────────────────────────────────────────

_STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "is", "are", "was", "be", "have", "has", "do", "does",
    "we", "our", "your", "their", "this", "that", "it", "its", "by", "as",
    "from", "up", "about", "into", "through", "during", "need", "needs",
    "should", "must", "will", "would", "can", "could", "may", "might",
    "shall", "system", "user", "users", "able", "allow", "allows", "provide",
    "support", "ensure", "use", "used", "using", "project", "solution",
}


def _extract_tags(text: str, max_tags: int = 15) -> list[str]:
    """Tokenise free text into lowercase keywords, excluding stop-words."""
    tokens = re.findall(r"[a-z][a-z0-9_-]{2,}", text.lower())
    seen: set[str] = set()
    tags: list[str] = []
    for t in tokens:
        if t not in _STOP_WORDS and t not in seen:
            seen.add(t)
            tags.append(t)
            if len(tags) >= max_tags:
                break
    return tags


def _content_hash(component_type: str, content: str) -> str:
    """SHA-256 fingerprint for deduplication (type + normalised content)."""
    normalised = " ".join(content.lower().split())
    return hashlib.sha256(f"{component_type}:{normalised}".encode()).hexdigest()


# ── Store helpers ─────────────────────────────────────────────────────────────


def store_component(
    db: Session,
    *,
    source_project_id: int | None,
    component_type: str,
    category: str,
    name: str,
    content: str,
    tags: list[str] | None = None,
    source: str = "auto",
    run_id: int | None = None,
) -> ComponentStore:
    """Persist a single reusable component.

    If *tags* is None, tags are auto-derived from *content*.
    content_hash is stored per-row for retrieval-time deduplication
    (the same text from multiple projects won't appear twice in results).
    """
    if tags is None:
        tags = _extract_tags(f"{name} {content}")

    component = ComponentStore(
        source_project_id=source_project_id,
        run_id=run_id,
        component_type=component_type,
        category=category,
        name=name,
        content=content,
        content_hash=_content_hash(component_type, content),
        tags_json=tags,
        source=source,
    )
    db.add(component)
    db.commit()
    db.refresh(component)
    return component


def bulk_store_components(
    db: Session,
    components: list[dict[str, Any]],
    *,
    run_id: int | None = None,
) -> list[ComponentStore]:
    """Persist multiple components in a single transaction.

    Each dict must have: source_project_id, component_type, category, name,
    content.  Optional: tags (list[str]), source (str).
    *run_id* is recorded on every row.
    """
    rows: list[ComponentStore] = []
    for c in components:
        ctype = c["component_type"]
        content = c["content"]
        tags = c.get("tags") or _extract_tags(f"{c['name']} {content}")
        rows.append(ComponentStore(
            source_project_id=c.get("source_project_id"),
            run_id=run_id,
            component_type=ctype,
            category=c.get("category", "general"),
            name=c["name"],
            content=content,
            content_hash=_content_hash(ctype, content),
            tags_json=tags,
            source=c.get("source", "auto"),
        ))
    db.add_all(rows)
    db.commit()
    for r in rows:
        db.refresh(r)
    return rows


# ── Retrieval ─────────────────────────────────────────────────────────────────

# Half-life in days for recency decay.  A component created 30 days ago
# scores ~0.71× relative to one created today; 90 days ago → ~0.36×.
_RECENCY_HALF_LIFE_DAYS = 30.0


def _recency_weight(created_at: datetime | None) -> float:
    """Exponential decay factor based on component age (0 < w ≤ 1.0)."""
    if created_at is None:
        return 0.5
    now = datetime.now(timezone.utc)
    # Make created_at timezone-aware if it isn't (SQLite returns naive datetimes)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (now - created_at).total_seconds() / 86400)
    # 2^(-age/half_life)
    return 2.0 ** (-age_days / _RECENCY_HALF_LIFE_DAYS)


def retrieve_relevant(
    db: Session,
    query_tags: list[str],
    *,
    component_types: list[str] | None = None,
    exclude_project_id: int | None = None,
    limit: int = 10,
    min_overlap: int = 1,
) -> list[dict[str, Any]]:
    """Return stored components most relevant to *query_tags*.

    Scoring = tag_overlap × recency_weight.  Ties broken by usage_count.

    Args:
        db:                 SQLAlchemy session.
        query_tags:         Keywords from the new project's intake message.
        component_types:    Optional allowlist of component_type values.
        exclude_project_id: Exclude components whose source_project_id matches
                            this value.  Pass the current project's id to
                            prevent circular self-reference at intake.
        limit:              Maximum number of results.
        min_overlap:        Minimum raw tag overlap to include a result.

    Returns:
        List of dicts with keys: id, component_type, category, name, content,
        tags, overlap, score, usage_count, source_project_id.
    """
    if not query_tags:
        return []

    query_set = set(t.lower() for t in query_tags)

    q = db.query(ComponentStore)
    if component_types:
        q = q.filter(ComponentStore.component_type.in_(component_types))
    if exclude_project_id is not None:
        q = q.filter(
            (ComponentStore.source_project_id != exclude_project_id)
            | (ComponentStore.source_project_id.is_(None))
        )

    candidates = q.all()

    scored: list[tuple[float, int, ComponentStore]] = []
    for c in candidates:
        stored_tags = set(t.lower() for t in (c.tags_json or []))
        overlap = len(query_set & stored_tags)
        if overlap < min_overlap:
            continue
        recency = _recency_weight(c.created_at)
        score = overlap * recency
        scored.append((score, c.usage_count, c))

    # Sort: descending composite score, then descending usage_count
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)

    # Retrieval-time deduplication: if multiple projects stored the same
    # content (same content_hash), keep only the best-scoring instance so
    # the same text never appears twice in results.
    seen_hashes: set[str] = set()
    deduped: list[tuple[float, int, ComponentStore]] = []
    for item in scored:
        h = item[2].content_hash or ""
        if h and h in seen_hashes:
            continue
        if h:
            seen_hashes.add(h)
        deduped.append(item)

    top = deduped[:limit]

    # Increment usage_count for retrieved components
    ids = [c.id for _, _, c in top]
    if ids:
        db.query(ComponentStore).filter(ComponentStore.id.in_(ids)).update(
            {ComponentStore.usage_count: ComponentStore.usage_count + 1},
            synchronize_session=False,
        )
        db.commit()

    return [
        {
            "id": c.id,
            "component_type": c.component_type,
            "category": c.category,
            "name": c.name,
            "content": c.content,
            "tags": c.tags_json,
            "overlap": int(score / _recency_weight(c.created_at)) if _recency_weight(c.created_at) else 0,
            "score": round(score, 4),
            "usage_count": c.usage_count,
            "source_project_id": c.source_project_id,
        }
        for score, _, c in top
    ]


def get_component(db: Session, component_id: int) -> ComponentStore | None:
    return db.query(ComponentStore).filter(ComponentStore.id == component_id).first()


def list_components(
    db: Session,
    *,
    component_type: str | None = None,
    category: str | None = None,
    source_project_id: int | None = None,
    source: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[ComponentStore]:
    q = db.query(ComponentStore)
    if component_type:
        q = q.filter(ComponentStore.component_type == component_type)
    if category:
        q = q.filter(ComponentStore.category == category)
    if source_project_id is not None:
        q = q.filter(ComponentStore.source_project_id == source_project_id)
    if source is not None:
        q = q.filter(ComponentStore.source == source)
    return q.order_by(ComponentStore.created_at.desc()).offset(offset).limit(limit).all()


def delete_component(db: Session, component_id: int) -> bool:
    c = get_component(db, component_id)
    if c is None:
        return False
    db.delete(c)
    db.commit()
    return True


# ── Auto-extraction from completed SoT ───────────────────────────────────────


def purge_auto_components(db: Session, project_id: int) -> int:
    """Delete all auto-extracted components for *project_id*.

    Called before re-extracting from a revised project so stale knowledge
    from old runs (e.g. PRD v1) is replaced by the latest SoT (PRD v2).
    Manual components (source='manual') are never touched.

    Returns the number of rows deleted.
    """
    deleted = (
        db.query(ComponentStore)
        .filter(
            ComponentStore.source_project_id == project_id,
            ComponentStore.source == "auto",
        )
        # "evaluate" keeps the session identity map in sync — deleted objects
        # are expelled from the map so recycled IDs never cause conflicts.
        .delete(synchronize_session="evaluate")
    )
    db.commit()
    return deleted


def auto_extract_and_store(
    db: Session,
    project_id: int,
    sot: dict[str, Any],
    *,
    run_id: int | None = None,
) -> list[ComponentStore]:
    """Extract reusable patterns from a completed project's SoT and store them.

    Called by end_node after a project is marked completed.

    **Revision handling**: purge_auto_components() is called unconditionally
    at the start — even when the revised SoT is empty.  This prevents stale
    v1 components from surviving a revision that stripped all content.

    **Deduplication**: components whose content already exists in the store
    (from any project) are silently skipped.

    Extracts:
      - requirements → "requirement_pattern"
      - decisions    → "architecture_decision"
      - risks        → "risk_pattern"
      - assumptions  → "assumption"
    """
    # Always purge first — even if the new SoT turns out to be empty.
    purge_auto_components(db, project_id)

    domain = sot.get("domain", "general")
    components: list[dict[str, Any]] = []

    # Requirements
    for req in sot.get("requirements", []):
        text = req.get("text", "")
        if not text:
            continue
        tags = [domain, req.get("category", "functional")] + _extract_tags(text)
        components.append({
            "source_project_id": project_id,
            "component_type": "requirement_pattern",
            "category": req.get("category", "functional"),
            "name": text[:120],
            "content": text,
            "tags": list(dict.fromkeys(tags)),
            "source": "auto",
        })

    # Architecture decisions
    for dec in sot.get("decisions", []):
        decision_text = dec.get("decision", "")
        rationale = dec.get("rationale", "")
        if not decision_text:
            continue
        combined = f"{decision_text}. {rationale}".strip()
        tags = [domain, "decision"] + _extract_tags(combined)
        components.append({
            "source_project_id": project_id,
            "component_type": "architecture_decision",
            "category": domain,
            "name": decision_text[:120],
            "content": combined,
            "tags": list(dict.fromkeys(tags)),
            "source": "auto",
        })

    # Risks
    for risk in sot.get("risks", []):
        desc = risk.get("description", "")
        mitigation = risk.get("mitigation", "")
        if not desc:
            continue
        combined = f"{desc}. Mitigation: {mitigation}".strip() if mitigation else desc
        tags = [domain, "risk", risk.get("likelihood", "medium")] + _extract_tags(desc)
        components.append({
            "source_project_id": project_id,
            "component_type": "risk_pattern",
            "category": domain,
            "name": desc[:120],
            "content": combined,
            "tags": list(dict.fromkeys(tags)),
            "source": "auto",
        })

    # Assumptions
    for assumption in sot.get("assumptions", []):
        text = assumption.get("text", "")
        if not text:
            continue
        tags = [domain, "assumption"] + _extract_tags(text)
        components.append({
            "source_project_id": project_id,
            "component_type": "assumption",
            "category": domain,
            "name": text[:120],
            "content": text,
            "tags": list(dict.fromkeys(tags)),
            "source": "auto",
        })

    # Tech stack decision (Gap 8)
    tech_stack = sot.get("tech_stack")
    if tech_stack and isinstance(tech_stack, dict):
        project_type = sot.get("project_type", "generic")
        ts_parts = [f"{k}: {v}" for k, v in tech_stack.items() if v]
        if ts_parts:
            ts_content = f"project_type={project_type}; " + "; ".join(ts_parts)
            tags = [domain, project_type, "tech_stack"] + _extract_tags(ts_content)
            components.append({
                "source_project_id": project_id,
                "component_type": "tech_stack_decision",
                "category": project_type,
                "name": f"Tech stack for {domain} ({project_type})",
                "content": ts_content,
                "tags": list(dict.fromkeys(tags)),
                "source": "auto",
            })

    # Architecture spec (API contracts + DB schema as code components) (Gap 8)
    arch_spec = sot.get("architecture_spec")
    if arch_spec and isinstance(arch_spec, dict):
        project_type = sot.get("project_type", "generic")

        # API contracts
        for contract in arch_spec.get("api_contracts", []):
            endpoint = f"{contract.get('method', 'GET')} {contract.get('path', '/')}"
            content = str(contract)
            tags = [domain, project_type, "api"] + _extract_tags(content)
            components.append({
                "source_project_id": project_id,
                "component_type": "api_contract",
                "category": project_type,
                "name": endpoint[:120],
                "content": content[:500],
                "tags": list(dict.fromkeys(tags)),
                "source": "auto",
            })

        # Database schema
        for table in arch_spec.get("database_schema", []):
            table_name = table.get("table", "unknown")
            content = str(table)
            tags = [domain, project_type, "database", table_name] + _extract_tags(content)
            components.append({
                "source_project_id": project_id,
                "component_type": "database_schema",
                "category": project_type,
                "name": f"Schema: {table_name}",
                "content": content[:500],
                "tags": list(dict.fromkeys(tags)),
                "source": "auto",
            })

    if not components:
        return []

    return bulk_store_components(db, components, run_id=run_id)


def build_context_summary(components: list[dict[str, Any]]) -> str:
    """Format retrieved components into a compact prompt-injection string."""
    if not components:
        return ""

    lines: list[str] = ["## Relevant patterns from past projects\n"]
    by_type: dict[str, list[dict]] = {}
    for c in components:
        by_type.setdefault(c["component_type"], []).append(c)

    type_labels = {
        "requirement_pattern": "Past requirements",
        "architecture_decision": "Architecture decisions",
        "risk_pattern": "Known risks",
        "assumption": "Common assumptions",
        "sow_template": "SOW templates",
        "prd_section": "PRD sections",
        # Code-specific component types (Gap 8)
        "code_template": "Code templates",
        "tech_stack_decision": "Tech stack decisions",
        "api_contract": "API contracts",
        "test_pattern": "Test patterns",
        "deployment_pattern": "Deployment patterns",
        "database_schema": "Database schemas",
    }

    for ctype, items in by_type.items():
        label = type_labels.get(ctype, ctype.replace("_", " ").title())
        lines.append(f"### {label}")
        for item in items:
            lines.append(f"- **{item['name']}**: {item['content'][:300]}")
        lines.append("")

    return "\n".join(lines)
