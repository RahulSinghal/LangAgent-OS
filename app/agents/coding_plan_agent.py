"""CodingPlanAgent — Step 4.

Divides the approved backlog into sequential, reviewable coding milestones
and raises a tech-lead approval gate before any code is written.

Responsibilities:
  1. Read requirements + scope + gathered backlog from SoT.
  2. Group work into 3–6 coherent milestones (LLM-driven).
  3. Set approvals_status["coding_plan"] = pending.
  4. On rejection (rejection_feedback present): incorporate reviewer comments
     and regenerate the plan.
  5. Clear rejection_feedback after processing.
"""

from __future__ import annotations

from app.agents.base import BaseAgent
from app.registry.loader import AgentLimits, AgentSpec
from app.sot.state import ApprovalStatus, MilestoneItem, ProjectState, _DEFAULT_EVALS


def _make_default_spec() -> AgentSpec:
    return AgentSpec(
        name="CodingPlanAgent",
        role="tech_lead",
        description=(
            "Divides the approved backlog into coding milestones "
            "for tech-lead sign-off before implementation begins."
        ),
        allowed_tools=[],
        limits=AgentLimits(max_steps=5, max_tool_calls=0, budget_usd=1.0),
    )


class CodingPlanAgent(BaseAgent):
    """Produces a milestone-based coding plan for tech lead approval."""

    def __init__(self, spec: AgentSpec | None = None) -> None:
        super().__init__(spec or _make_default_spec())

    # ── BaseAgent interface ────────────────────────────────────────────────────

    def run(self, state: ProjectState) -> dict:
        """Generate milestone plan and set coding_plan approval to pending."""
        from app.services.llm_service import call_llm_json  # lazy

        feedback_ctx = self._feedback_context(state)
        milestones = self._generate_plan(state, call_llm_json, feedback_ctx)

        approvals = {k: v.value for k, v in state.approvals_status.items()}
        approvals["coding_plan"] = ApprovalStatus.PENDING.value

        return {
            "current_phase": "coding",
            "coding_plan": [m.model_dump() for m in milestones],
            "current_milestone_index": 0,
            "approvals_status": approvals,
            "rejection_feedback": None,
        }

    # ── Private helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _feedback_context(state: ProjectState) -> str:
        fb = state.rejection_feedback
        if fb and fb.get("artifact_type") == "coding_plan":
            comment = fb.get("comment", "").strip()
            if comment:
                return f"\n\nREJECTION FEEDBACK TO ADDRESS:\n{comment}"
        return ""

    def _generate_plan(
        self,
        state: ProjectState,
        call_llm_json,
        feedback_ctx: str,
    ) -> list[MilestoneItem]:
        """LLM: divide the backlog into ordered, independently-deliverable milestones."""
        past_ctx = self._past_context_block(state.past_context)
        project_type = state.project_type or "generic"
        type_hint = self._project_type_ordering_hint(project_type)
        tech_ctx = self._tech_stack_hint(state)
        eval_defaults = _DEFAULT_EVALS.get(project_type, _DEFAULT_EVALS["generic"])

        system = (
            "You are a senior tech lead planning a software delivery. "
            "Divide the approved work into logical, sequential coding milestones.\n\n"
            f"Project type: {project_type}\n"
            + type_hint
            + tech_ctx
            + past_ctx
            + "Return a JSON array. Each item:\n"
            '{"name": "...", "description": "...", "stories": ["story ref 1", ...]}\n\n'
            "Guidelines:\n"
            "- 3–6 milestones total.\n"
            "- Each milestone must be independently deliverable and reviewable.\n"
            "- Follow the project-type ordering above.\n"
            "- stories lists the specific backlog items covered by that milestone."
            + feedback_ctx
        )
        context = (
            f"Project Scope:\n{state.scope}\n\n"
            f"Requirements (top 20):\n"
            + "\n".join(f"- {r.text}" for r in state.requirements[:20])
            + f"\n\nBacklog:\n{state.gathered_requirements.get('backlog', 'Not yet defined')}"
        )
        try:
            result = call_llm_json(system, context)
            items = result if isinstance(result, list) else result.get("milestones", [])
            return [
                MilestoneItem(
                    name=m.get("name", f"Milestone {i + 1}"),
                    description=m.get("description", ""),
                    stories=m.get("stories", []),
                    expected_evals=eval_defaults,
                )
                for i, m in enumerate(items)
                if isinstance(m, dict)
            ]
        except Exception:
            return []

    @staticmethod
    def _project_type_ordering_hint(project_type: str) -> str:
        hints = {
            "rag_pipeline": (
                "Ordering for RAG pipeline:\n"
                "1. Data ingestion + chunking pipeline\n"
                "2. Embedding pipeline + vector store setup\n"
                "3. Retrieval chain + LLM orchestration\n"
                "4. API gateway + eval harness\n\n"
            ),
            "web_app": (
                "Ordering for web application:\n"
                "1. Database models + migrations + auth backend\n"
                "2. Core API routes + business logic\n"
                "3. Frontend components + pages\n"
                "4. Integrations + deployment config\n\n"
            ),
            "crm": (
                "Ordering for CRM:\n"
                "1. Org hierarchy + user/role models + permissions\n"
                "2. Lead/contact/pipeline management\n"
                "3. Activity log + workflow triggers\n"
                "4. Reporting + integrations\n\n"
            ),
            "voice_chatbot": (
                "Ordering for voice chatbot:\n"
                "1. Telephony webhook + session management\n"
                "2. NLU intent classification + dialogue state machine\n"
                "3. TTS integration + response generation\n"
                "4. Analytics + fallback handling + human escalation\n\n"
            ),
            "generic": (
                "Ordering: foundational (infra/data/auth) → core features → "
                "integrations → polish.\n\n"
            ),
        }
        return hints.get(project_type, hints["generic"])

    @staticmethod
    def _tech_stack_hint(state: ProjectState) -> str:
        ts = state.tech_stack
        if not ts:
            return ""
        parts = [f"{k}={v}" for k, v in ts.model_dump().items() if v]
        if not parts:
            return ""
        return "Tech stack: " + ", ".join(parts) + "\n\n"
