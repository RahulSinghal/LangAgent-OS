"""UserGuideAgent — Optional post-SOW step.

Generates a project-specific end-user guide in Markdown after the user
confirms they want one (user_guide_requested=True).

The generated content covers:
  1. Project overview and purpose
  2. Getting started / installation & setup
  3. Key features and how to use them (user workflows)
  4. API reference summary (if applicable)
  5. Configuration reference (.env variables)
  6. Troubleshooting common issues
  7. Glossary (domain-specific terms)

Project-type awareness drives the content focus:
  - rag_pipeline: query syntax, source attribution, embedding config
  - web_app:      navigation, user roles, common workflows
  - crm:          lead/contact management, pipeline stages, reporting
  - voice_chatbot: call flow, intent phrases, escalation, recording

The generated guide is stored in sot.user_guide_content and then rendered
as an artifact ("user_guide") by the run engine via render_artifact().
"""

from __future__ import annotations

from app.agents.base import BaseAgent
from app.registry.loader import AgentLimits, AgentSpec
from app.sot.state import ProjectState


# ── Project-type content hints ────────────────────────────────────────────────

_GUIDE_FOCUS: dict[str, str] = {
    "rag_pipeline": (
        "Focus areas for RAG pipeline user guide:\n"
        "- How to submit queries and interpret answers with source citations\n"
        "- How to ingest new documents (supported formats, upload steps)\n"
        "- Configuring embedding models and vector store settings\n"
        "- Understanding retrieval quality metrics and how to improve them\n"
        "- Common failure modes (no results, hallucinations) and fixes"
    ),
    "web_app": (
        "Focus areas for web application user guide:\n"
        "- Account registration, login, and profile management\n"
        "- Navigation structure and key pages\n"
        "- Role-based access: what each role can and cannot do\n"
        "- Core user workflows step-by-step (with screenshots placeholder text)\n"
        "- Browser compatibility and performance tips"
    ),
    "crm": (
        "Focus areas for CRM user guide:\n"
        "- Creating and managing leads, contacts, and accounts\n"
        "- Pipeline stages and how to advance a deal\n"
        "- Activity logging (calls, emails, meetings)\n"
        "- Reporting and dashboard interpretation\n"
        "- User roles and permission boundaries\n"
        "- Integration with email/calendar"
    ),
    "voice_chatbot": (
        "Focus areas for voice chatbot user guide:\n"
        "- How to interact with the bot (supported commands and phrases)\n"
        "- Call flow walkthrough (greeting → intent → resolution → escalation)\n"
        "- Escalation to a human agent: when and how it happens\n"
        "- Admin guide: adding new intents and updating scripts\n"
        "- Analytics: interpreting call logs and intent match rates"
    ),
    "generic": (
        "Focus areas: system overview, setup, core features, configuration, troubleshooting."
    ),
}


def _make_default_spec() -> AgentSpec:
    return AgentSpec(
        name="UserGuideAgent",
        role="technical_writer",
        description=(
            "Generates a project-specific end-user guide in Markdown after the "
            "user confirms they want one (post-SOW, pre-coding)."
        ),
        allowed_tools=[],
        limits=AgentLimits(max_steps=3, max_tool_calls=0, budget_usd=1.5),
    )


class UserGuideAgent(BaseAgent):
    """Generates a comprehensive project-specific user guide."""

    def __init__(self, spec: AgentSpec | None = None) -> None:
        super().__init__(spec or _make_default_spec())

    # ── BaseAgent interface ────────────────────────────────────────────────────

    def run(self, state: ProjectState) -> dict:
        """Generate user guide and store in SoT."""
        from app.services.llm_service import call_llm  # lazy

        guide_md = self._generate_guide(state, call_llm)
        return {
            "user_guide_content": guide_md,
            "current_phase": "user_guide",
        }

    # ── Private helpers ────────────────────────────────────────────────────────

    def _generate_guide(self, state: ProjectState, call_llm) -> str:
        """LLM: generate user guide markdown for this specific project."""
        project_type = state.project_type or "generic"
        focus = _GUIDE_FOCUS.get(project_type, _GUIDE_FOCUS["generic"])

        system = (
            "You are a senior technical writer creating a user guide for a software project.\n\n"
            f"Project type: {project_type}\n"
            f"{focus}\n\n"
            "Write a comprehensive, well-structured user guide in Markdown.\n\n"
            "Required sections:\n"
            "1. # Overview — what the system does and who it is for\n"
            "2. # Getting Started — prerequisites, installation, initial setup\n"
            "3. # Key Features — explain each major feature with step-by-step usage\n"
            "4. # Configuration Reference — all environment variables with descriptions\n"
            "5. # API Reference — key endpoints with request/response examples (if applicable)\n"
            "6. # Troubleshooting — common issues and solutions\n"
            "7. # Glossary — domain-specific terms explained\n\n"
            "Rules:\n"
            "- Use clear, non-technical language for end-user sections\n"
            "- Use technical precision for admin/config sections\n"
            "- Include realistic examples specific to this project\n"
            "- Do NOT use generic placeholders like [Company Name] — use the actual project context\n"
            "- Format code examples with fenced code blocks"
        )
        context = (
            f"Project Scope:\n{state.scope}\n\n"
            f"Key requirements:\n"
            + "\n".join(f"- {r.text}" for r in state.requirements[:20])
            + (
                f"\n\nTech stack: {state.tech_stack.model_dump()}"
                if state.tech_stack else ""
            )
            + (
                f"\n\nAPI contracts: {state.architecture_spec.api_contracts[:5]}"
                if state.architecture_spec and state.architecture_spec.api_contracts else ""
            )
        )

        try:
            return call_llm(system, context)
        except Exception:
            return (
                "# User Guide\n\n"
                "> User guide generation encountered an error. "
                "Please regenerate after reviewing the project scope.\n"
            )
