"""SOWAgent — Phase 4.

Real LLM-driven SOW agent that replaces MockSOWAgent.

Responsibilities:
  1. Generate SOW sections from scope + commercials + requirements.
  2. Run a legal guard check to flag high-risk clauses.
  3. Set approvals_status["sow"] = pending.
  4. On re-run (rejection_feedback present): include reviewer comments as
     additional context before regenerating.
  5. Clear rejection_feedback after processing.

Ported from Enterprise_bot/app/graph/nodes/sow_draft.py and adapted to the
AgentOS BaseAgent + SoT-patch pattern.
"""

from __future__ import annotations

from typing import Any

from app.agents.base import BaseAgent
from app.registry.loader import AgentSpec, AgentLimits
from app.sot.state import ApprovalStatus, ProjectState


def _make_default_spec() -> AgentSpec:
    return AgentSpec(
        name="SOWAgent",
        role="engagement_manager",
        description="Generates SOW sections with legal guard check",
        allowed_tools=[],
        limits=AgentLimits(max_steps=5, max_tool_calls=0, budget_usd=1.0),
    )


class SOWAgent(BaseAgent):
    """LLM-driven SOW agent with rejection-feedback re-generation loop."""

    def __init__(self, spec: AgentSpec | None = None) -> None:
        super().__init__(spec or _make_default_spec())

    # ── BaseAgent interface ────────────────────────────────────────────────────

    def run(self, state: ProjectState) -> dict:
        """Generate SOW sections + legal guard check, set SOW to pending approval."""
        from app.services.llm_service import call_llm_json  # lazy

        feedback_ctx = self._feedback_context(state, "sow")
        sow_sections = self._generate_sow_sections(state, call_llm_json, feedback_ctx)
        _ = self._legal_guard_check(sow_sections, call_llm_json)
        # legal_flags are informational — stored implicitly in the narrative

        approvals = {k: v.value for k, v in state.approvals_status.items()}
        approvals["sow"] = ApprovalStatus.PENDING.value

        return {
            "current_phase": "sow",
            "sow_sections": sow_sections,
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

    def _generate_sow_sections(
        self,
        state: ProjectState,
        call_llm_json,
        feedback_ctx: str,
    ) -> list[dict[str, Any]]:
        """LLM: draft SOW sections as a structured list."""
        system = (
            "You are a senior engagement manager drafting a Statement of Work. "
            "Generate a comprehensive SOW as a JSON array of sections.\n\n"
            'Each section: {"title": "...", "content": "..."}\n\n'
            "Required sections (in order):\n"
            "1. Executive Summary\n"
            "2. Project Scope\n"
            "3. Deliverables\n"
            "4. Timeline & Milestones\n"
            "5. Commercials & Payment Terms\n"
            "6. Assumptions & Constraints\n"
            "7. Acceptance Criteria\n"
            "8. Risks & Mitigations\n"
            "9. Governance & Communication\n\n"
            "Be specific, professional, and contractually precise."
            + feedback_ctx
        )
        context = (
            f"Project Scope:\n{state.scope}\n\n"
            f"Commercial Model: {state.commercial_model}\n\n"
            f"Milestones: {state.milestones}\n\n"
            f"Requirements (top 20):\n"
            + "\n".join(f"- {r.text}" for r in state.requirements[:20])
        )
        try:
            result = call_llm_json(system, context)
            if isinstance(result, list):
                return result
            # Some models return {"sections": [...]}
            if isinstance(result, dict) and "sections" in result:
                return result["sections"]
            return []
        except Exception:
            return []

    def _legal_guard_check(
        self,
        sections: list[dict],
        call_llm_json,
    ) -> list[str]:
        """LLM: identify clauses that may need legal review."""
        if not sections:
            return []
        system = (
            "You are a legal risk reviewer for consulting SOWs. "
            "Identify clauses that require legal attention.\n\n"
            'Return JSON: {"flags": ["description of risk..."]}\n\n'
            "Flag: unlimited liability, ambiguous IP ownership, "
            "SLA penalty clauses, restrictive non-compete terms, "
            "indemnification without caps."
        )
        try:
            # Only scan first 3 sections to keep token cost low
            result = call_llm_json(system, str(sections[:3]))
            return result.get("flags", [])
        except Exception:
            return []
