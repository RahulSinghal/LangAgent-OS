"""PRDAgent — Phase 4.

Real LLM-driven PRD agent that replaces MockPRDAgent.

Responsibilities:
  1. Generate a structured project scope from gathered requirements.
  2. Set approvals_status["prd"] = pending so the gate node pauses the run.
  3. On re-run (rejection_feedback present): incorporate reviewer comments
     into the LLM context before regenerating scope + PRD content.
  4. Clear rejection_feedback after processing so the gate sees a clean state.

Note: Artifact rendering (Jinja2 → file) is handled by _process_result in
runs.py when pause_reason == "waiting_approval".  PRDAgent itself stays
side-effect-free and fully unit-testable without file I/O.
"""

from __future__ import annotations

from typing import Any

from app.agents.base import BaseAgent
from app.registry.loader import AgentSpec, AgentLimits
from app.sot.state import ApprovalStatus, ProjectState


def _make_default_spec() -> AgentSpec:
    return AgentSpec(
        name="PRDAgent",
        role="product_manager",
        description="Generates scope and PRD from gathered requirements",
        allowed_tools=[],
        limits=AgentLimits(max_steps=5, max_tool_calls=0, budget_usd=1.0),
    )


class PRDAgent(BaseAgent):
    """LLM-driven PRD agent with rejection-feedback re-generation loop."""

    def __init__(self, spec: AgentSpec | None = None) -> None:
        super().__init__(spec or _make_default_spec())

    # ── BaseAgent interface ────────────────────────────────────────────────────

    def run(self, state: ProjectState) -> dict:
        """Generate scope, set PRD to pending approval, clear any rejection feedback."""
        from app.services.llm_service import call_llm, call_llm_json  # lazy

        feedback_ctx = self._feedback_context(state, "prd")

        scope = self._generate_scope(state, call_llm_json, feedback_ctx)
        _ = self._generate_prd_narrative(state, scope, call_llm, feedback_ctx)
        # narrative is informational; artifact rendering is done by _process_result

        approvals = {k: v.value for k, v in state.approvals_status.items()}
        approvals["prd"] = ApprovalStatus.PENDING.value
        # Conditional server-details approval routing:
        # - client hosting → client must approve server details
        # - vendor hosting → infra team must approve server details
        hp = (state.hosting_preference or "client").lower().strip()
        if hp in ("client", "client_server", "client-hosted", "self_hosted", "self-hosted", "own_server"):
            approvals["server_details_client"] = ApprovalStatus.PENDING.value
            approvals.pop("server_details_infra", None)
        else:
            approvals["server_details_infra"] = ApprovalStatus.PENDING.value
            approvals.pop("server_details_client", None)

        return {
            "current_phase": "prd",
            "scope": scope,
            "approvals_status": approvals,
            "rejection_feedback": None,  # consumed — clear for next gate check
        }

    # ── Private helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _feedback_context(state: ProjectState, artifact_type: str) -> str:
        """Build an extra context block from rejection_feedback (if any)."""
        fb = state.rejection_feedback
        if fb and fb.get("artifact_type") == artifact_type:
            comment = fb.get("comment", "").strip()
            if comment:
                return f"\n\nREJECTION FEEDBACK TO ADDRESS:\n{comment}"
        return ""

    def _generate_scope(
        self,
        state: ProjectState,
        call_llm_json,
        feedback_ctx: str,
    ) -> dict[str, Any]:
        """LLM: generate a structured project scope from requirements."""
        system = (
            "You are a senior business analyst. "
            "Generate a structured project scope from the gathered requirements.\n\n"
            "Return JSON:\n"
            '{"summary": "one-sentence description", '
            '"in_scope": ["..."], '
            '"out_of_scope": ["..."], '
            '"key_deliverables": ["..."], '
            '"constraints": ["..."], '
            '"success_criteria": ["..."]}'
            + feedback_ctx
        )
        requirements_text = "\n".join(f"- {r.text}" for r in state.requirements)
        try:
            result = call_llm_json(
                system,
                f"Requirements:\n{requirements_text}\n\n"
                f"Gathered requirements detail:\n{state.gathered_requirements}",
            )
            # Validate minimal structure
            if isinstance(result, dict) and "summary" in result:
                return result
            return _empty_scope()
        except Exception:
            return _empty_scope()

    def _generate_prd_narrative(
        self,
        state: ProjectState,
        scope: dict,
        call_llm,
        feedback_ctx: str,
    ) -> str:
        """LLM: write a PRD narrative from the scope and requirements."""
        system = (
            "You are a product manager. Write a concise PRD narrative.\n"
            "Include sections: Executive Summary, User Personas, "
            "Functional Requirements, Non-Functional Requirements, "
            "Out of Scope.\n"
            "Be precise and professional." + feedback_ctx
        )
        reqs_text = "\n".join(f"- {r.text}" for r in state.requirements[:30])
        try:
            return call_llm(
                system,
                f"Scope:\n{scope}\n\nRequirements:\n{reqs_text}",
            )
        except Exception:
            return "PRD narrative generation failed — please retry."


def _empty_scope() -> dict[str, Any]:
    return {
        "summary": "To be defined",
        "in_scope": [],
        "out_of_scope": [],
        "key_deliverables": [],
        "constraints": [],
        "success_criteria": [],
    }
