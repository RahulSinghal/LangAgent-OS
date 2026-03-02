"""Mock CommercialAgent — deterministic, no LLM required."""

from __future__ import annotations

from app.agents.base import BaseAgent
from app.registry.loader import AgentLimits, AgentSpec
from app.sot.state import ApprovalStatus, ProjectState


def _mock_spec() -> AgentSpec:
    return AgentSpec(
        name="MockCommercialAgent",
        role="engagement_manager",
        description="Mock CommercialAgent for testing",
        allowed_tools=[],
        limits=AgentLimits(max_steps=2, max_tool_calls=0, budget_usd=0.0),
    )


class MockCommercialAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(_mock_spec())

    def run(self, state: ProjectState) -> dict:
        approvals = {k: v.value for k, v in state.approvals_status.items()}
        approvals["commercials"] = ApprovalStatus.PENDING.value
        return {
            "current_phase": "commercials",
            "commercial_model": "Fixed Price (mock)",
            "milestones": [],
            "approvals_status": approvals,
        }

