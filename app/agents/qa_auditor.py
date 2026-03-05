"""QAAuditorAgent — Phase 2 implementation.

Validates PRD/SOW artifacts for completeness:
  - PRD: must have acceptance criteria + NFRs
  - SOW: must have exclusions + milestones + change control clause

The auditor is advisory — it appends missing-element flags to open_questions
so reviewers see them at the approval gate. It never blocks the workflow
directly; that responsibility stays with the human reviewer.
"""

from __future__ import annotations

from app.agents.base import BaseAgent
from app.registry.loader import AgentLimits, AgentSpec
from app.sot.state import ProjectState, QuestionItem


def _make_default_spec() -> AgentSpec:
    return AgentSpec(
        name="QAAuditorAgent",
        role="qa_auditor",
        description="Validates PRD and SOW artifacts for completeness",
        allowed_tools=[],
        limits=AgentLimits(max_steps=3, max_tool_calls=0, budget_usd=0.5),
    )


class QAAuditorAgent(BaseAgent):
    """LLM-driven quality auditor that checks PRD/SOW completeness.

    Appends any gaps it finds to state.open_questions so they surface
    during the approval review.  Returns an empty patch if nothing is wrong.
    """

    def __init__(self, spec: AgentSpec | None = None) -> None:
        super().__init__(spec or _make_default_spec())

    # ── BaseAgent interface ────────────────────────────────────────────────────

    def run(self, state: ProjectState) -> dict:
        """Check the most recently generated artifact and flag gaps."""
        from app.services.llm_service import call_llm_json  # lazy

        issues: list[str] = []

        if state.scope:
            issues += self._audit_prd(state, call_llm_json)

        if state.sow_sections:
            issues += self._audit_sow(state, call_llm_json)

        if not issues:
            return {}

        new_questions = list(state.open_questions)
        for issue in issues:
            new_questions.append(
                QuestionItem(
                    question=issue,
                    category="qa_audit",
                    answered=False,
                )
            )
        return {"open_questions": [q.model_dump() for q in new_questions]}

    # ── Private helpers ────────────────────────────────────────────────────────

    def _audit_prd(self, state: ProjectState, call_llm_json) -> list[str]:
        """LLM: check PRD scope for acceptance criteria and NFRs."""
        system = (
            "You are a QA auditor reviewing a PRD scope for completeness.\n\n"
            "Check whether the scope includes:\n"
            "  1. Acceptance criteria (how the client will verify each deliverable)\n"
            "  2. Non-functional requirements (performance, security, scalability, etc.)\n\n"
            'Return JSON: {"missing": ["description of each gap"], "ok": true/false}\n\n'
            "If both are present return {\"missing\": [], \"ok\": true}. "
            "Be concise — one short sentence per gap."
        )
        try:
            result = call_llm_json(system, f"Scope:\n{state.scope}")
            missing = result.get("missing", []) if isinstance(result, dict) else []
            return [f"[PRD QA] {m}" for m in missing if m]
        except Exception:
            return []

    def _audit_sow(self, state: ProjectState, call_llm_json) -> list[str]:
        """LLM: check SOW sections for exclusions, milestones, and change control."""
        system = (
            "You are a QA auditor reviewing a Statement of Work for completeness.\n\n"
            "Check whether the SOW explicitly includes:\n"
            "  1. Out-of-scope exclusions (what is NOT covered)\n"
            "  2. Milestones or delivery timeline\n"
            "  3. Change control clause (how scope changes are handled)\n\n"
            'Return JSON: {"missing": ["description of each gap"], "ok": true/false}\n\n'
            "If all three are present return {\"missing\": [], \"ok\": true}. "
            "Be concise — one short sentence per gap."
        )
        # Only scan first 5 sections to keep token cost low
        sections_preview = state.sow_sections[:5]
        try:
            result = call_llm_json(system, f"SOW sections:\n{sections_preview}")
            missing = result.get("missing", []) if isinstance(result, dict) else []
            return [f"[SOW QA] {m}" for m in missing if m]
        except Exception:
            return []
