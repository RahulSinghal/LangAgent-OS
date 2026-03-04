"""Coding milestone node — Step 4.

Runs MilestoneCodeAgent for coding_plan[current_milestone_index].

This node is re-entered for every milestone:
  - After coding_plan approval    → first execution (index 0)
  - After milestone approval      → index advances, same node runs again
  - After milestone rejection     → same index, agent incorporates feedback

The milestone_gate conditional edge decides whether to loop back here
(next_milestone / rejected) or proceed to the next phase (all_done).
"""

from __future__ import annotations

from app.agents.milestone_code_agent import MilestoneCodeAgent
from app.agents.mock_agents import MockMilestoneCodeAgent
from app.core.runtime import use_mock_agents
from app.sot.state import ProjectState


def coding_milestone_phase(state: dict) -> dict:
    """Execute MilestoneCodeAgent for the current milestone index.

    Args:
        state: WorkflowState dict.

    Returns:
        Partial WorkflowState update with updated SoT.
    """
    sot = ProjectState(**state["sot"])
    agent = MockMilestoneCodeAgent() if use_mock_agents() else MilestoneCodeAgent()
    new_sot = agent.execute(sot)
    return {
        "sot": new_sot.model_dump_jsonb(),
        "pause_reason": None,
        "bot_response": None,
    }
