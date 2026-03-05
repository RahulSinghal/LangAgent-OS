"""ScaffoldAgent — Step 4 (post-code).

Generates project scaffolding files after all milestone code is approved:
  - Dockerfile (with multi-stage build)
  - requirements.txt / package.json (pinned dependencies)
  - .env.example (all required environment variables)
  - docker-compose.yml (local dev environment)
  - GitHub Actions CI/CD workflow (.github/workflows/ci.yml)
  - README.md (project overview, setup, usage)
  - .gitignore

Project-type awareness drives which services are included in docker-compose
(e.g. Chroma/Pinecone for RAG, Asterisk/Twilio mock for voice, etc.).
"""

from __future__ import annotations

from app.agents.base import BaseAgent
from app.registry.loader import AgentLimits, AgentSpec
from app.sot.state import CodeFile, MilestoneItem, ProjectState, TechStackSpec


# ── Project-type scaffold hints ────────────────────────────────────────────────

_SCAFFOLD_HINTS: dict[str, str] = {
    "rag_pipeline": (
        "Include: vector store service (Chroma or pgvector), embedding worker, "
        "API server. docker-compose should run the vector DB alongside the app. "
        ".env.example must include OPENAI_API_KEY, VECTOR_STORE_URL, EMBEDDING_MODEL."
    ),
    "web_app": (
        "Include: frontend build stage (Node.js), backend API server, PostgreSQL. "
        "docker-compose should run DB + API + frontend dev server. "
        ".env.example must include DATABASE_URL, JWT_SECRET, CORS_ORIGINS."
    ),
    "crm": (
        "Include: PostgreSQL (with org hierarchy schema), Redis (for sessions/queues), "
        "API server. .env.example must include DATABASE_URL, REDIS_URL, JWT_SECRET, "
        "SMTP settings for notifications."
    ),
    "voice_chatbot": (
        "Include: Webhook server (for telephony provider), Redis (session store), "
        "optional ngrok for local dev. .env.example must include TWILIO_ACCOUNT_SID, "
        "TWILIO_AUTH_TOKEN, TTS_API_KEY, NLU_ENDPOINT, REDIS_URL."
    ),
    "generic": (
        "Include standard application stack: API server, PostgreSQL, Redis. "
        ".env.example must include DATABASE_URL, SECRET_KEY, LOG_LEVEL."
    ),
}


def _make_default_spec() -> AgentSpec:
    return AgentSpec(
        name="ScaffoldAgent",
        role="devops",
        description=(
            "Generates Dockerfile, docker-compose.yml, .env.example, CI/CD workflow, "
            "requirements.txt and README after all milestones are approved."
        ),
        allowed_tools=["write_file"],
        limits=AgentLimits(max_steps=5, max_tool_calls=15, budget_usd=1.0),
    )


class ScaffoldAgent(BaseAgent):
    """Generates project scaffolding files and writes them to disk."""

    def __init__(self, spec: AgentSpec | None = None) -> None:
        super().__init__(spec or _make_default_spec())

    # ── BaseAgent interface ────────────────────────────────────────────────────

    def run(self, state: ProjectState) -> dict:
        """Generate scaffold files and write them via the tool gateway."""
        from app.services.llm_service import call_llm_json  # lazy

        project_type = state.project_type or "generic"
        scaffold_files = self._generate_scaffold(state, call_llm_json, project_type)
        written = self._write_scaffold_files(state.project_id, scaffold_files)

        # Store scaffold file list on the last milestone for reference
        plan = [m.model_dump() for m in state.coding_plan]
        if plan:
            last = plan[-1]
            existing_files = last.get("code_files", [])
            scaffold_dicts = [f.model_dump() for f in written]
            last["code_files"] = existing_files + scaffold_dicts
            plan[-1] = last

        return {
            "coding_plan": plan,
            "current_phase": "milestone",
        }

    # ── Private helpers ────────────────────────────────────────────────────────

    def _generate_scaffold(
        self,
        state: ProjectState,
        call_llm_json,
        project_type: str,
    ) -> list[dict]:
        """LLM: generate all scaffolding file contents."""
        hint = _SCAFFOLD_HINTS.get(project_type, _SCAFFOLD_HINTS["generic"])
        tech_ctx = self._tech_stack_context(state.tech_stack)

        system = (
            "You are a senior DevOps engineer generating project scaffolding.\n\n"
            f"Project type: {project_type}\n"
            f"{hint}\n\n"
            + tech_ctx
            + "Return a JSON array of files. Each item:\n"
            '{"path": "relative/path", "language": "dockerfile|yaml|text|markdown", '
            '"content": "...", "description": "..."}\n\n'
            "Required files:\n"
            "1. Dockerfile (multi-stage build)\n"
            "2. docker-compose.yml (local dev with all services)\n"
            "3. .env.example (all required env vars with descriptions)\n"
            "4. .gitignore (Python + Node + env files)\n"
            "5. .github/workflows/ci.yml (lint + test + build)\n"
            "6. README.md (overview, setup, usage, env vars table)\n"
            "7. requirements.txt or package.json (with pinned versions)\n"
            "Write real, production-quality content — not placeholders."
        )
        context = (
            f"Project Scope:\n{state.scope}\n\n"
            "Requirements (top 10):\n"
            + "\n".join(f"- {r.text}" for r in state.requirements[:10])
        )
        try:
            result = call_llm_json(system, context)
            files = result if isinstance(result, list) else result.get("files", [])
            return [
                f for f in files
                if isinstance(f, dict) and "path" in f and "content" in f
            ]
        except Exception:
            return []

    def _write_scaffold_files(
        self,
        project_id: int,
        scaffold_files: list[dict],
    ) -> list[CodeFile]:
        """Write scaffold files via tool gateway and return CodeFile records."""
        if not scaffold_files:
            return []

        base = f"storage/artifacts/{project_id}/scaffold"
        written: list[CodeFile] = []
        for f in scaffold_files:
            path = f"{base}/{f['path'].lstrip('/')}"
            result = self.call_tool("write_file", {"path": path, "content": f["content"]})
            if result.success:
                written.append(CodeFile(
                    path=f["path"],
                    language=f.get("language", "text"),
                    content=f["content"],
                    description=f.get("description", ""),
                ))
        return written

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
