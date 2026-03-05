"""Readiness phase node — Phase 3.

Runs ReadinessAgent to generate the deployment readiness checklist and
collect cloud/infra preferences before final project handover.
"""

from __future__ import annotations

from app.agents.readiness_agent import ReadinessAgent
from app.core.runtime import use_mock_agents
from app.sot.state import ProjectState


def readiness_phase(state: dict) -> dict:
    """Execute ReadinessAgent and update SoT with readiness phase state.

    Args:
        state: WorkflowState dict.

    Returns:
        Partial WorkflowState update with updated SoT.
    """
    sot = ProjectState(**state["sot"])

    # No mock variant for readiness — the agent is lightweight enough that
    # the real LLM call is always used.  USE_MOCK_AGENTS bypasses it entirely
    # so contract/integration tests can skip this phase.
    if use_mock_agents():
        from app.sot.patch import apply_patch
        from app.sot.state import ApprovalStatus
        approvals = {k: v.value for k, v in sot.approvals_status.items()}
        approvals["readiness"] = ApprovalStatus.PENDING.value
        new_sot = apply_patch(sot, {
            "current_phase": "readiness",
            "approvals_status": approvals,
        })
    else:
        new_sot = ReadinessAgent().execute(sot)

    return {
        "sot": new_sot.model_dump_jsonb(),
        "pause_reason": None,
        "bot_response": None,
    }
