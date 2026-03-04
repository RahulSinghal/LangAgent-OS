"""End node — Phase 1E.

Marks the run as completed by setting current_phase = "completed".
The run engine saves the final snapshot and updates runs.status after invoke().

Cross-project memory: auto-extracts reusable patterns (requirements, decisions,
risks, assumptions) from the completed SoT and persists them to ComponentStore
so future projects can benefit from institutional knowledge.
"""

from __future__ import annotations

import structlog

from app.sot.patch import apply_patch
from app.sot.state import ProjectState

logger = structlog.get_logger(__name__)


def end_node(state: dict) -> dict:
    """Finalise the run — set phase to completed and harvest reusable patterns.

    Args:
        state: WorkflowState dict.

    Returns:
        Partial WorkflowState update with phase=completed and no pause.
    """
    sot = ProjectState(**state["sot"])
    completed = apply_patch(sot, {"current_phase": "completed"})
    sot_dict = completed.model_dump_jsonb()

    # Auto-extract reusable patterns into the cross-project ComponentStore.
    # Best-effort: never block completion on extraction errors.
    try:
        from app.db.session import SessionLocal
        from app.services.context_retrieval import auto_extract_and_store

        db = SessionLocal()
        try:
            extracted = auto_extract_and_store(db, sot.project_id, sot_dict)
            if extracted:
                logger.info(
                    "memory.extracted",
                    project_id=sot.project_id,
                    count=len(extracted),
                )
        finally:
            db.close()
    except Exception:
        logger.exception("memory.extract_failed", project_id=sot.project_id)

    return {
        "sot": sot_dict,
        "pause_reason": None,
        "bot_response": "Engagement complete. All artifacts are approved.",
    }
