"""Architecture node — Step 4 (pre-code).

Runs ArchitectureAgent after coding_plan approval and before the first
MilestoneCodeAgent execution.  Generates the ArchitectureSpec (file tree,
API contracts, DB schema, milestone→file map) that MilestoneCodeAgent reads.
"""

from __future__ import annotations

from app.agents.architecture_agent import ArchitectureAgent
from app.sot.state import ProjectState


def architecture_phase(state: dict) -> dict:
    """Execute ArchitectureAgent and store ArchitectureSpec in SoT.

    Args:
        state: WorkflowState dict.

    Returns:
        Partial WorkflowState update with updated SoT.
    """
    sot = ProjectState(**state["sot"])
    agent = ArchitectureAgent()
    new_sot = agent.execute(sot)
    return {
        "sot": new_sot.model_dump_jsonb(),
        "pause_reason": None,
        "bot_response": None,
    }
