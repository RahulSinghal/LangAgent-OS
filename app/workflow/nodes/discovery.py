"""Discovery loop node — Phase 4.

Runs the real DiscoveryAgent (LLM-driven) instead of MockDiscoveryAgent.

Termination logic (Phase 4):
  - DiscoveryAgent.run() returns discovery_complete=True when ALL coverage
    scores reach _COVERAGE_THRESHOLD (0.7).
  - If BRD/PRD/SOW/tech-design gap followup_questions are present, those are
    asked first.
  - After each user answer, requirements are extracted and coverage updated.
  - When discovery_complete is True:
      - If document_type maps to a specific phase (prd, sow, market_eval,
        commercials) → set current_phase to that phase so the entry router and
        _process_result() both see the correct phase when the graph is paused.
      - The _route_after_discovery conditional edge then fast-tracks to the
        appropriate gate or generator node, skipping intermediate phases.
      - technical_design is handled by the edge directly (no phase override
        here; the coding_plan node sets Phase.CODING itself).
      - brd / unknown → normal continue to market_eval.
"""

from __future__ import annotations

from app.agents.discovery_agent import DiscoveryAgent
from app.agents.mock_agents import MockDiscoveryAgent
from app.core.runtime import use_mock_agents
from app.sot.state import ProjectState


# Maps document_type to the target current_phase that the gate node expects.
# Gates rely on current_phase being set correctly so that _process_result()
# stores the right current_node and resume routing works on subsequent calls.
# technical_design is excluded: the coding_plan generator node sets CODING itself.
_DOC_TYPE_PHASE: dict[str, str] = {
    "market_eval": "market_eval",
    "prd":         "prd",
    "commercials": "commercials",
    "sow":         "sow",
}


def discovery_loop(state: dict) -> dict:
    """Run DiscoveryAgent and route to pause or continue.

    When discovery completes and document_type indicates a specific phase,
    current_phase is advanced to that phase so that:
      1. The graph conditional edge fast-tracks to the correct gate/node.
      2. _process_result() records the right current_node (e.g. "prd_gate").
      3. On resume, _route_entry() lands at the right gate without re-running
         discovery.

    Args:
        state: WorkflowState dict.

    Returns:
        Partial WorkflowState update with updated SoT and optional pause signal.
    """
    sot = ProjectState(**state["sot"])

    agent = MockDiscoveryAgent() if use_mock_agents() else DiscoveryAgent()
    new_sot = agent.execute(sot)

    # Discovery complete — fast-track if an input document maps to a later phase
    if new_sot.discovery_complete:
        target_phase = _DOC_TYPE_PHASE.get(new_sot.document_type or "")
        if target_phase:
            from app.sot.patch import apply_patch
            new_sot = apply_patch(new_sot, {"current_phase": target_phase})
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
