"""Intake node — Phase 1E.

Normalises the raw user input into the SoT and transitions phase to discovery.
This node runs only once per run (on start); resumes skip it via entry router.

Cross-project memory: queries ComponentStore for patterns relevant to the
incoming project and injects them into sot.past_context so agents can
leverage institutional knowledge from past projects.
"""

from __future__ import annotations

import structlog

from app.sot.patch import apply_patch
from app.sot.state import ProjectState, detect_project_type

logger = structlog.get_logger(__name__)


def intake_normalize(state: dict) -> dict:
    """Normalise raw user input, set phase=discovery, inject past context.

    Args:
        state: WorkflowState dict.

    Returns:
        Partial WorkflowState update.
    """
    sot = ProjectState(**state["sot"])

    # Transition to discovery phase; keep last_user_message for agent context.
    # Also set hosting_preference using lightweight heuristics so downstream
    # gates can route server-details approvals deterministically without LLMs.
    msg = (sot.last_user_message or "").lower()
    hp = sot.hosting_preference
    if any(k in msg for k in ("on your server", "on our server", "your server", "upload on your", "host it for us")):
        hp = "vendor"
    if any(k in msg for k in ("own server", "our own server", "self hosted", "self-hosted", "client hosted", "client-hosted")):
        hp = "client"

    # ── Cross-project memory retrieval ────────────────────────────────────────
    # Extract keywords from the incoming message and domain, then fetch
    # relevant patterns from ComponentStore.  Best-effort — never block intake.
    past_context: list[dict] = []
    try:
        from app.db.session import SessionLocal
        from app.services.context_retrieval import retrieve_relevant, _extract_tags

        query_tags = _extract_tags(f"{msg} {sot.domain}")
        if query_tags:
            db = SessionLocal()
            try:
                past_context = retrieve_relevant(
                    db,
                    query_tags=query_tags,
                    exclude_project_id=sot.project_id,
                    limit=12,
                    min_overlap=1,
                )
                if past_context:
                    logger.info(
                        "memory.injected",
                        project_id=sot.project_id,
                        count=len(past_context),
                    )
            finally:
                db.close()
    except Exception:
        logger.exception("memory.inject_failed", project_id=sot.project_id)

    # Detect project type from the initial message (heuristic — overridable later)
    project_type = sot.project_type
    if project_type == "generic" and msg:
        project_type = detect_project_type(msg)

    updated = apply_patch(
        sot,
        {
            "current_phase": "discovery",
            "hosting_preference": hp,
            "past_context": past_context,
            "project_type": project_type,
        },
    )

    return {
        "sot": updated.model_dump_jsonb(),
        "pause_reason": None,
        "bot_response": None,
    }
