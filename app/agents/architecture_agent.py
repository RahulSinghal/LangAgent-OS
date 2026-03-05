"""ArchitectureAgent — Step 4 (pre-code).

Generates an ArchitectureSpec before any code is written:
  - File tree (all files the project will contain)
  - API contracts (endpoints, inputs, outputs)
  - Database schema (tables/collections)
  - Milestone-to-file mapping (which files belong to which milestone)

This agent runs once, between CodingPlanAgent approval and the first
MilestoneCodeAgent execution. MilestoneCodeAgent reads milestone_file_map
to know exactly which files it must produce for each milestone.

Project-type awareness:
  - rag_pipeline  → includes vector store client, embedder, retriever, chain
  - web_app       → includes routes, components, auth middleware, static assets
  - crm           → includes org hierarchy, role model, workflow engine
  - voice_chatbot → includes telephony webhook, NLU handler, dialogue manager
  - generic       → standard layered architecture
"""

from __future__ import annotations

from app.agents.base import BaseAgent
from app.registry.loader import AgentLimits, AgentSpec
from app.sot.state import ArchitectureSpec, ProjectState, TechStackSpec


# ── Project-type architecture templates ───────────────────────────────────────

_ARCH_HINTS: dict[str, str] = {
    "rag_pipeline": (
        "Architecture style: RAG pipeline.\n"
        "Required layers: data ingestion, embedding pipeline, vector store client, "
        "retrieval chain, LLM orchestration, API gateway, evaluation harness.\n"
        "Key files: ingest.py, embedder.py, retriever.py, chain.py, api/routes.py, "
        "evals/retrieval_eval.py."
    ),
    "web_app": (
        "Architecture style: layered web application.\n"
        "Required layers: frontend (components, pages, routing), backend (API routes, "
        "services, middleware), database (models, migrations), auth (JWT/OAuth middleware).\n"
        "Key files: frontend/App.tsx, api/routes/, services/, models/, migrations/, "
        "middleware/auth.py."
    ),
    "crm": (
        "Architecture style: CRM domain model.\n"
        "Required layers: org hierarchy (company/team/user), lead/contact management, "
        "pipeline stages, activity log, role-permission engine, workflow triggers.\n"
        "Key files: models/org.py, models/lead.py, models/pipeline.py, "
        "services/permissions.py, services/workflow.py, api/crm_routes.py."
    ),
    "voice_chatbot": (
        "Architecture style: voice dialogue system.\n"
        "Required layers: telephony webhook handler (Twilio/Vonage), NLU processor, "
        "dialogue state machine, TTS synthesizer, session store.\n"
        "Key files: webhooks/inbound_call.py, nlu/intent_classifier.py, "
        "dialogue/state_machine.py, tts/synthesizer.py, session/store.py."
    ),
    "generic": (
        "Architecture style: standard layered application.\n"
        "Required layers: API/routes, services/business logic, data models, utilities.\n"
        "Key files: api/, services/, models/, utils/, tests/."
    ),
}


def _make_default_spec() -> AgentSpec:
    return AgentSpec(
        name="ArchitectureAgent",
        role="architect",
        description=(
            "Generates file tree, API contracts, DB schema, and milestone-to-file "
            "mapping before code generation begins. Project-type aware."
        ),
        allowed_tools=[],
        limits=AgentLimits(max_steps=5, max_tool_calls=0, budget_usd=1.5),
    )


class ArchitectureAgent(BaseAgent):
    """Produces an ArchitectureSpec for tech-lead review before codegen."""

    def __init__(self, spec: AgentSpec | None = None) -> None:
        super().__init__(spec or _make_default_spec())

    # ── BaseAgent interface ────────────────────────────────────────────────────

    def run(self, state: ProjectState) -> dict:
        """Generate ArchitectureSpec and return it as a SoT patch."""
        from app.services.llm_service import call_llm_json  # lazy

        spec = self._generate_spec(state, call_llm_json)
        return {
            "architecture_spec": spec.model_dump(),
            "current_phase": "coding",
        }

    # ── Private helpers ────────────────────────────────────────────────────────

    def _generate_spec(self, state: ProjectState, call_llm_json) -> ArchitectureSpec:
        project_type = state.project_type or "generic"
        arch_hint = _ARCH_HINTS.get(project_type, _ARCH_HINTS["generic"])
        tech_ctx = self._tech_stack_context(state.tech_stack)
        past_ctx = self._past_context_block(state.past_context)
        milestone_names = [m.name for m in state.coding_plan] if state.coding_plan else []

        system = (
            "You are a senior software architect.\n\n"
            f"Project type: {project_type}\n"
            f"{arch_hint}\n\n"
            + tech_ctx
            + past_ctx
            + "Return a JSON object with:\n"
            '{\n'
            '  "style": "<architecture style>",\n'
            '  "file_tree": ["relative/path/to/file.py", ...],\n'
            '  "api_contracts": [\n'
            '    {"method": "POST", "path": "/api/query", "request": {...}, "response": {...}},\n'
            '    ...\n'
            '  ],\n'
            '  "database_schema": [\n'
            '    {"table": "users", "columns": [{"name": "id", "type": "uuid"}, ...]},\n'
            '    ...\n'
            '  ],\n'
            '  "milestone_file_map": {\n'
            '    "<milestone_name>": ["path/to/file1.py", "path/to/file2.py"],\n'
            '    ...\n'
            '  }\n'
            '}\n\n'
            "Rules:\n"
            "- file_tree must list EVERY file the project will contain.\n"
            "- milestone_file_map keys must match the milestone names exactly.\n"
            "- Each file must appear in exactly one milestone.\n"
            "- Include test files, config files (Dockerfile, .env.example, README.md).\n"
            "- Keep paths relative (no leading slash)."
        )
        context = (
            f"Project Scope:\n{state.scope}\n\n"
            f"Coding milestones: {milestone_names}\n\n"
            "Requirements (top 15):\n"
            + "\n".join(f"- {r.text}" for r in state.requirements[:15])
        )

        try:
            raw = call_llm_json(system, context)
            return ArchitectureSpec(
                style=raw.get("style", "layered"),
                file_tree=raw.get("file_tree", []),
                api_contracts=raw.get("api_contracts", []),
                database_schema=raw.get("database_schema", []),
                milestone_file_map=raw.get("milestone_file_map", {}),
            )
        except Exception:
            return ArchitectureSpec(style=project_type)

    @staticmethod
    def _tech_stack_context(tech_stack: TechStackSpec | None) -> str:
        if not tech_stack:
            return ""
        parts = []
        for field, value in tech_stack.model_dump().items():
            if value:
                parts.append(f"  {field}: {value}")
        if not parts:
            return ""
        return "Tech stack:\n" + "\n".join(parts) + "\n\n"
