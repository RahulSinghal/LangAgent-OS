"""End node — Phase 1E.

Marks the run as completed by setting current_phase = "completed".
The run engine saves the final snapshot and updates runs.status after invoke().
"""

from __future__ import annotations

from app.sot.patch import apply_patch
from app.sot.state import ProjectState


def end_node(state: dict) -> dict:
    """Finalise the run — set phase to completed.

    Args:
        state: WorkflowState dict.

    Returns:
        Partial WorkflowState update with phase=completed and no pause.
    """
    sot = ProjectState(**state["sot"])
    completed = apply_patch(sot, {"current_phase": "completed"})

    return {
        "sot": completed.model_dump_jsonb(),
        "pause_reason": None,
        "bot_response": "Engagement complete. All artifacts are approved.",
    }
