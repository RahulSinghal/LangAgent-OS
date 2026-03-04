"""Coding plan node — Step 4.

Runs CodingPlanAgent to divide the approved SOW backlog into sequential,
independently-reviewable coding milestones.

The node transitions current_phase to "coding" and sets the coding_plan
approval to pending, which causes the graph to pause at coding_plan_gate
for tech lead sign-off.
"""

from __future__ import annotations

from app.agents.coding_plan_agent import CodingPlanAgent
from app.agents.mock_agents import MockCodingPlanAgent
from app.core.runtime import use_mock_agents
from app.sot.state import ProjectState


def coding_plan_phase(state: dict) -> dict:
    """Execute CodingPlanAgent and update SoT with the proposed milestone plan.

    Args:
        state: WorkflowState dict.

    Returns:
        Partial WorkflowState update with updated SoT.
    """
    sot = ProjectState(**state["sot"])
    agent = MockCodingPlanAgent() if use_mock_agents() else CodingPlanAgent()
    new_sot = agent.execute(sot)
    return {
        "sot": new_sot.model_dump_jsonb(),
        "pause_reason": None,
        "bot_response": None,
    }
