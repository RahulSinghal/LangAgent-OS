"""User guide node — optional post-SOW step.

This node sits between sow_gate approval and coding_plan.

Flow:
  1. First entry (user_guide_requested is None):
       Ask the user: "Would you like a user guide generated for this project?"
       Set current_phase = "user_guide" and pause with waiting_user.

  2. Re-entry (user responds via last_user_message):
       Parse yes/no from the user's answer.
       - "yes" → run UserGuideAgent → render artifact → continue to coding_plan
       - "no"  → skip guide generation → continue to coding_plan

The graph re-enters this node on resume because _route_entry maps
"user_guide" → "user_guide".
"""

from __future__ import annotations

import re

import structlog

from app.sot.patch import apply_patch
from app.sot.state import ProjectState

logger = structlog.get_logger(__name__)

_YES_RE = re.compile(r"\b(yes|yep|yeah|sure|ok|okay|please|generate|create|make|want)\b", re.IGNORECASE)
_NO_RE  = re.compile(r"\b(no|nope|nah|skip|don'?t|not now|later|pass)\b", re.IGNORECASE)

_QUESTION = (
    "Would you like me to generate a **User Guide** for this project? "
    "It will be a comprehensive end-user document covering setup, features, "
    "configuration, and troubleshooting — saved as an artifact on your dashboard.\n\n"
    "Reply **yes** to generate it now, or **no** to skip."
)


def user_guide_phase(state: dict) -> dict:
    """Ask user if they want a guide; generate it on confirmation.

    Args:
        state: WorkflowState dict.

    Returns:
        Partial WorkflowState update with updated SoT and optional pause signal.
    """
    sot = ProjectState(**state["sot"])

    # ── First entry: ask the user ──────────────────────────────────────────────
    if sot.user_guide_requested is None and not sot.last_user_message:
        updated = apply_patch(sot, {"current_phase": "user_guide"})
        return {
            "sot": updated.model_dump_jsonb(),
            "pause_reason": "waiting_user",
            "bot_response": _QUESTION,
        }

    # ── Re-entry: parse the user's answer ─────────────────────────────────────
    msg = (sot.last_user_message or "").strip()

    if msg:
        wants_guide = bool(_YES_RE.search(msg)) and not bool(_NO_RE.search(msg))
        # If only negatives found → skip
        if not _YES_RE.search(msg) and _NO_RE.search(msg):
            wants_guide = False
        # Default to yes if the user just said something ambiguous
        if not _YES_RE.search(msg) and not _NO_RE.search(msg):
            wants_guide = False  # ambiguous → skip to avoid blocking workflow

        patch: dict = {
            "user_guide_requested": wants_guide,
            "last_user_message": None,  # consume
        }

        if wants_guide:
            # Run the UserGuideAgent and render the artifact
            try:
                from app.agents.user_guide_agent import UserGuideAgent
                guide_sot = apply_patch(sot, patch)
                guide_sot = UserGuideAgent().execute(guide_sot)
                # Render to disk + DB
                _render_user_guide_artifact(guide_sot, state.get("run_id"))
                return {
                    "sot": guide_sot.model_dump_jsonb(),
                    "pause_reason": None,
                    "bot_response": (
                        "User guide generated and saved to your project artifacts. "
                        "Moving on to the coding plan."
                    ),
                }
            except Exception:
                logger.exception("user_guide.generation_failed", project_id=sot.project_id)
                # Never block the workflow on guide failure
                fallback = apply_patch(sot, patch)
                return {
                    "sot": fallback.model_dump_jsonb(),
                    "pause_reason": None,
                    "bot_response": "User guide generation encountered an error — skipping. Proceeding to coding plan.",
                }
        else:
            updated = apply_patch(sot, patch)
            return {
                "sot": updated.model_dump_jsonb(),
                "pause_reason": None,
                "bot_response": "Skipping user guide. Moving on to the coding plan.",
            }

    # ── Edge case: re-entered without a message (shouldn't happen) ─────────────
    updated = apply_patch(sot, {"current_phase": "user_guide"})
    return {
        "sot": updated.model_dump_jsonb(),
        "pause_reason": "waiting_user",
        "bot_response": _QUESTION,
    }


def _render_user_guide_artifact(sot: ProjectState, run_id: int | None) -> None:
    """Persist user guide content as an Artifact record (best-effort)."""
    try:
        from app.db.session import SessionLocal
        from app.artifacts.generator import render_artifact

        db = SessionLocal()
        try:
            render_artifact("user_guide", sot, db, run_id=run_id)
        finally:
            db.close()
    except Exception:
        logger.exception("user_guide.render_failed", project_id=sot.project_id)
