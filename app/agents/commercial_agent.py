"""CommercialAgent — Phase 4.

New agent: generates a commercial proposal (pricing model, milestones, team
composition) between PRD approval and SOW drafting.

Ported from Enterprise_bot/app/graph/nodes/commercials.py and adapted to the
AgentOS BaseAgent + SoT-patch pattern.
"""

from __future__ import annotations

from typing import Any

from app.agents.base import BaseAgent
from app.registry.loader import AgentSpec, AgentLimits
from app.sot.state import ApprovalStatus, ProjectState


def _make_default_spec() -> AgentSpec:
    return AgentSpec(
        name="CommercialAgent",
        role="engagement_manager",
        description="Generates commercial proposals with pricing and milestones",
        allowed_tools=[],
        limits=AgentLimits(max_steps=5, max_tool_calls=0, budget_usd=1.0),
    )


class CommercialAgent(BaseAgent):
    """LLM-driven commercials agent with rejection-feedback re-generation loop."""

    def __init__(self, spec: AgentSpec | None = None) -> None:
        super().__init__(spec or _make_default_spec())

    # ── BaseAgent interface ────────────────────────────────────────────────────

    def run(self, state: ProjectState) -> dict:
        """Generate commercial proposal, set commercials to pending approval."""
        from app.services.llm_service import call_llm_json  # lazy

        feedback_ctx = self._feedback_context(state, "commercials")
        commercials = self._generate_commercials(state, call_llm_json, feedback_ctx)

        approvals = {k: v.value for k, v in state.approvals_status.items()}
        approvals["commercials"] = ApprovalStatus.PENDING.value

        return {
            "current_phase": "commercials",
            "commercial_model": commercials.get("commercial_model", ""),
            "milestones": commercials.get("milestones", []),
            "approvals_status": approvals,
            "rejection_feedback": None,  # consumed
        }

    # ── Private helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _feedback_context(state: ProjectState, artifact_type: str) -> str:
        fb = state.rejection_feedback
        if fb and fb.get("artifact_type") == artifact_type:
            comment = fb.get("comment", "").strip()
            if comment:
                return f"\n\nREJECTION FEEDBACK TO ADDRESS:\n{comment}"
        return ""

    def _generate_commercials(
        self,
        state: ProjectState,
        call_llm_json,
        feedback_ctx: str,
    ) -> dict[str, Any]:
        """LLM: generate pricing model, milestones, team composition."""
        system = (
            "You are an experienced engagement manager at a consulting firm. "
            "Generate a commercial proposal for the described project.\n\n"
            "Return JSON:\n"
            '{"commercial_model": "T&M | Fixed | Hybrid — brief description", '
            '"milestones": [{"name": "...", "duration": "...", '
            '"deliverables": ["..."], "payment_pct": 25}], '
            '"team_composition": [{"role": "...", "count": 1, "rate_range": "..."}], '
            '"total_estimate": "£X – £Y over N months", '
            '"payment_terms": "30 days net", '
            '"assumptions": ["..."]}'
            + feedback_ctx
        )
        scope_text = str(state.scope or {})
        reqs_text = "\n".join(f"- {r.text}" for r in state.requirements[:20])
        try:
            result = call_llm_json(
                system,
                f"Project scope:\n{scope_text}\n\nRequirements:\n{reqs_text}",
            )
            if isinstance(result, dict):
                return result
            return _empty_commercials()
        except Exception:
            return _empty_commercials()


def _empty_commercials() -> dict[str, Any]:
    return {
        "commercial_model": "To be determined",
        "milestones": [],
        "team_composition": [],
        "total_estimate": "TBD",
        "payment_terms": "TBD",
        "assumptions": [],
    }
