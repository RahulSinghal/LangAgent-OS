"""Commercials phase node — Phase 4.

Runs CommercialAgent to generate a commercial proposal (pricing model,
milestones, team composition) and transitions the SoT to commercials phase.
"""

from __future__ import annotations

from app.agents.commercial_agent import CommercialAgent
from app.agents.mock_commercial import MockCommercialAgent
from app.core.runtime import use_mock_agents
from app.sot.state import ProjectState


def commercials_phase(state: dict) -> dict:
    """Execute CommercialAgent and update SoT with commercial proposal.

    Args:
        state: WorkflowState dict.

    Returns:
        Partial WorkflowState update with updated SoT.
    """
    sot = ProjectState(**state["sot"])

    agent = MockCommercialAgent() if use_mock_agents() else CommercialAgent()
    new_sot = agent.execute(sot)

    return {
        "sot": new_sot.model_dump_jsonb(),
        "pause_reason": None,
        "bot_response": None,
    }
