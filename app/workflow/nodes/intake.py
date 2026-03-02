"""Intake node — Phase 1E.

Normalises the raw user input into the SoT and transitions phase to discovery.
This node runs only once per run (on start); resumes skip it via entry router.
"""

from __future__ import annotations

from app.sot.patch import apply_patch
from app.sot.state import ProjectState


def intake_normalize(state: dict) -> dict:
    """Normalise raw user input, set phase=discovery.

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

    updated = apply_patch(sot, {"current_phase": "discovery", "hosting_preference": hp})

    return {
        "sot": updated.model_dump_jsonb(),
        "pause_reason": None,
        "bot_response": None,
    }
