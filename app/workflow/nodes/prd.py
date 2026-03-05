"""PRD phase node — Phase 4.

Runs the real PRDAgent (LLM-driven) instead of MockPRDAgent.
Artifact rendering (Jinja2 → file) is handled by _process_result in runs.py.
"""

from __future__ import annotations

import logging

from app.agents.prd_agent import PRDAgent
from app.agents.mock_agents import MockPRDAgent
from app.agents.qa_auditor import QAAuditorAgent
from app.core.runtime import use_mock_agents
from app.sot.state import ProjectState

_log = logging.getLogger(__name__)


def prd_phase(state: dict) -> dict:
    """Execute PRDAgent (then QAAuditorAgent) and update SoT.

    Args:
        state: WorkflowState dict.

    Returns:
        Partial WorkflowState update with updated SoT.

    Raises:
        ValueError: Re-raised if the agent returns a malformed patch, so the
                    run engine can mark the run as 'error' rather than leaving
                    it stuck in 'running'.
    """
    sot = ProjectState(**state["sot"])

    agent = MockPRDAgent() if use_mock_agents() else PRDAgent()
    try:
        new_sot = agent.execute(sot)
    except ValueError as exc:
        _log.error("PRDAgent returned a malformed patch (run_id=%s): %s", state.get("run_id"), exc)
        raise

    # QA audit runs in real mode only — advisory, never blocks.
    if not use_mock_agents():
        try:
            new_sot = QAAuditorAgent().execute(new_sot)
        except Exception:
            # QA audit failure must never block the workflow.
            pass

    return {
        "sot": new_sot.model_dump_jsonb(),
        "pause_reason": None,
        "bot_response": None,
    }
