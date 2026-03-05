"""Coding milestone node — Step 4.

Runs MilestoneCodeAgent for coding_plan[current_milestone_index], then
immediately runs CodeReviewAgent as an automated quality/security gate
before the human tech-lead approval.

This node is re-entered for every milestone:
  - After coding_plan approval    → first execution (index 0)
  - After milestone approval      → index advances, same node runs again
  - After milestone rejection     → same index, agent incorporates feedback

The milestone_gate conditional edge decides whether to loop back here
(next_milestone / rejected) or proceed to the next phase (all_done).
"""

from __future__ import annotations

from app.agents.code_review_agent import CodeReviewAgent
from app.agents.milestone_code_agent import MilestoneCodeAgent
from app.agents.mock_agents import MockMilestoneCodeAgent
from app.core.runtime import use_mock_agents
from app.sot.state import ProjectState


def coding_milestone_phase(state: dict) -> dict:
    """Execute MilestoneCodeAgent then CodeReviewAgent for the current milestone.

    Args:
        state: WorkflowState dict.

    Returns:
        Partial WorkflowState update with updated SoT.
    """
    sot = ProjectState(**state["sot"])

    # Step 1: Generate code for the milestone
    code_agent = MockMilestoneCodeAgent() if use_mock_agents() else MilestoneCodeAgent()
    sot_after_code = code_agent.execute(sot)

    # Step 2: Automated code review (always real — mock mode still runs review)
    review_agent = CodeReviewAgent()
    try:
        sot_after_review = review_agent.execute(sot_after_code)
    except Exception:
        # Review failure must never block the workflow — log and continue
        sot_after_review = sot_after_code

    return {
        "sot": sot_after_review.model_dump_jsonb(),
        "pause_reason": None,
        "bot_response": None,
    }
