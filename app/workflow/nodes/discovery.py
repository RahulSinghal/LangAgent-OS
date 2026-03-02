"""Discovery loop node — Phase 4.

Runs the real DiscoveryAgent (LLM-driven) instead of MockDiscoveryAgent.

Termination logic (Phase 4):
  - DiscoveryAgent.run() returns discovery_complete=True when ALL coverage
    scores reach _COVERAGE_THRESHOLD (0.7).
  - If BRD/PRD/SOW gap followup_questions are present, those are asked first.
  - After each user answer, requirements are extracted and coverage updated.
  - When discovery_complete is True → continue to market_eval.
  - Otherwise → pause and surface the most recently added question.
"""

from __future__ import annotations

from app.agents.discovery_agent import DiscoveryAgent
from app.agents.mock_agents import MockDiscoveryAgent
from app.core.runtime import use_mock_agents
from app.sot.state import ProjectState


def discovery_loop(state: dict) -> dict:
    """Run DiscoveryAgent and route to pause or continue.

    Args:
        state: WorkflowState dict.

    Returns:
        Partial WorkflowState update with updated SoT and optional pause signal.
    """
    sot = ProjectState(**state["sot"])

    agent = MockDiscoveryAgent() if use_mock_agents() else DiscoveryAgent()
    new_sot = agent.execute(sot)

    # Discovery complete — proceed to market evaluation
    if new_sot.discovery_complete:
        return {
            "sot": new_sot.model_dump_jsonb(),
            "pause_reason": None,
            "bot_response": None,
        }

    # Not yet complete — surface the most recently added unanswered question
    unanswered = [q for q in new_sot.open_questions if not q.answered]
    question_text = (
        unanswered[-1].question
        if unanswered
        else "Can you tell me more about your requirements?"
    )

    return {
        "sot": new_sot.model_dump_jsonb(),
        "pause_reason": "waiting_user",
        "bot_response": question_text,
    }
