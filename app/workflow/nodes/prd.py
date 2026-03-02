"""PRD phase node — Phase 4.

Runs the real PRDAgent (LLM-driven) instead of MockPRDAgent.
Artifact rendering (Jinja2 → file) is handled by _process_result in runs.py.
"""

from __future__ import annotations

from app.agents.prd_agent import PRDAgent
from app.agents.mock_agents import MockPRDAgent
from app.core.runtime import use_mock_agents
from app.sot.state import ProjectState


def prd_phase(state: dict) -> dict:
    """Execute PRDAgent and update SoT with PRD phase state.

    Args:
        state: WorkflowState dict.

    Returns:
        Partial WorkflowState update with updated SoT.
    """
    sot = ProjectState(**state["sot"])

    agent = MockPRDAgent() if use_mock_agents() else PRDAgent()
    new_sot = agent.execute(sot)

    return {
        "sot": new_sot.model_dump_jsonb(),
        "pause_reason": None,
        "bot_response": None,
    }
