"""Cross-project context retrieval service.

Provides two main capabilities:

1. store_component() / bulk_store_components()
   Save reusable patterns, templates, and decisions to ComponentStore.

2. retrieve_relevant()
   Given a set of keyword tags (derived from a new project's message/domain),
   return the most relevant stored components ranked by tag-overlap score and
   descending usage count.

3. auto_extract_and_store()
   Called by end_node when a project completes.  Walks the final SoT and
   extracts requirement patterns, architecture decisions, risks, and
   assumptions, then persists them to ComponentStore.

Tag-based retrieval is intentionally simple (no embeddings required) so the
system works without any additional ML infrastructure.  Semantic/embedding
retrieval can be layered on top later by adding an embedding column and a
cosine-similarity step.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.db.models import ComponentStore


# ── Stop-words (excluded from auto-tagging) ───────────────────────────────────

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
) -> ComponentStore:
    """Persist a single reusable component.

    If *tags* is None, tags are auto-derived from *content*.
    """
    if tags is None:
        tags = _extract_tags(f"{name} {content}")
    component = ComponentStore(
        source_project_id=source_project_id,
        component_type=component_type,
        category=category,
        name=name,
        content=content,
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
) -> list[ComponentStore]:
    """Persist multiple components in a single transaction.

    Each dict in *components* must have: source_project_id, component_type,
    category, name, content.  Optional: tags (list[str]), source (str).
    """
    rows: list[ComponentStore] = []
    for c in components:
        tags = c.get("tags") or _extract_tags(f"{c['name']} {c['content']}")
        rows.append(ComponentStore(
            source_project_id=c.get("source_project_id"),
            component_type=c["component_type"],
            category=c.get("category", "general"),
            name=c["name"],
            content=c["content"],
            tags_json=tags,
            source=c.get("source", "auto"),
        ))
    db.add_all(rows)
    db.commit()
    for r in rows:
        db.refresh(r)
    return rows


# ── Retrieval ─────────────────────────────────────────────────────────────────


def retrieve_relevant(
    db: Session,
    query_tags: list[str],
    *,
    component_types: list[str] | None = None,
    limit: int = 10,
    min_overlap: int = 1,
) -> list[dict[str, Any]]:
    """Return stored components most relevant to *query_tags*.

    Relevance = number of tags shared between the query and the component's
    tags_json list.  Ties are broken by descending usage_count.

    Args:
        db:              SQLAlchemy session.
        query_tags:      Keywords extracted from the new project's intake message.
        component_types: Optional allowlist of component_type values.
        limit:           Maximum number of results.
        min_overlap:     Minimum shared-tag count to include a result.

    Returns:
        List of dicts with keys: id, component_type, category, name, content,
        tags, overlap, usage_count, source_project_id.
    """
    if not query_tags:
        return []

    query_set = set(t.lower() for t in query_tags)

    q = db.query(ComponentStore)
    if component_types:
        q = q.filter(ComponentStore.component_type.in_(component_types))

    candidates = q.order_by(ComponentStore.usage_count.desc()).all()

    scored: list[tuple[int, ComponentStore]] = []
    for c in candidates:
        stored_tags = set(t.lower() for t in (c.tags_json or []))
        overlap = len(query_set & stored_tags)
        if overlap >= min_overlap:
            scored.append((overlap, c))

    # Sort: descending overlap, then descending usage_count
    scored.sort(key=lambda x: (x[0], x[1].usage_count), reverse=True)
    top = scored[:limit]

    # Increment usage_count for retrieved components
    ids = [c.id for _, c in top]
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
            "overlap": overlap,
            "usage_count": c.usage_count,
            "source_project_id": c.source_project_id,
        }
        for overlap, c in top
    ]


def get_component(db: Session, component_id: int) -> ComponentStore | None:
    return db.query(ComponentStore).filter(ComponentStore.id == component_id).first()


def list_components(
    db: Session,
    *,
    component_type: str | None = None,
    category: str | None = None,
    source_project_id: int | None = None,
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
    return q.order_by(ComponentStore.created_at.desc()).offset(offset).limit(limit).all()


def delete_component(db: Session, component_id: int) -> bool:
    c = get_component(db, component_id)
    if c is None:
        return False
    db.delete(c)
    db.commit()
    return True


# ── Auto-extraction from completed SoT ───────────────────────────────────────


def auto_extract_and_store(
    db: Session,
    project_id: int,
    sot: dict[str, Any],
) -> list[ComponentStore]:
    """Extract reusable patterns from a completed project's SoT and store them.

    Called by end_node after a project is marked completed.

    Extracts:
      - requirements → "requirement_pattern"
      - decisions    → "architecture_decision"
      - risks        → "risk_pattern"
      - assumptions  → "assumption"

    Each item is tagged with the project domain plus keywords from its text.
    """
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
            "tags": list(dict.fromkeys(tags)),  # deduplicate, preserve order
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

    if not components:
        return []

    return bulk_store_components(db, components)


def build_context_summary(components: list[dict[str, Any]]) -> str:
    """Format retrieved components into a compact prompt-injection string.

    Agents can prepend this to their system prompt to leverage past knowledge.
    """
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
    }

    for ctype, items in by_type.items():
        label = type_labels.get(ctype, ctype.replace("_", " ").title())
        lines.append(f"### {label}")
        for item in items:
            lines.append(f"- **{item['name']}**: {item['content'][:300]}")
        lines.append("")

    return "\n".join(lines)
