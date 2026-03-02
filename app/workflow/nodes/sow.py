"""SOW phase node — Phase 4.

Runs the real SOWAgent (LLM-driven) instead of MockSOWAgent.
Artifact rendering (Jinja2 → file) is handled by _process_result in runs.py.
"""

from __future__ import annotations

from app.agents.sow_agent import SOWAgent
from app.agents.mock_agents import MockSOWAgent
from app.core.runtime import use_mock_agents
from app.sot.state import ProjectState


def sow_phase(state: dict) -> dict:
    """Execute SOWAgent and update SoT with SOW phase state.

    Args:
        state: WorkflowState dict.

    Returns:
        Partial WorkflowState update with updated SoT.
    """
    sot = ProjectState(**state["sot"])

    agent = MockSOWAgent() if use_mock_agents() else SOWAgent()
    new_sot = agent.execute(sot)

    return {
        "sot": new_sot.model_dump_jsonb(),
        "pause_reason": None,
        "bot_response": None,
    }
