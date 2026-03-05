"""MilestoneCodeAgent — Step 4.

Generates production-quality code for a single coding milestone and raises
a per-milestone tech-lead review gate.

Execution model:
  1. Read coding_plan[current_milestone_index] from SoT.
  2. LLM: generate code files for that milestone.
  3. Write files to disk via write_file tool (gateway-enforced).
  4. Mark milestone status = "in_progress" in coding_plan.
  5. Set approvals_status["milestone_{id}"] = pending for tech lead review.
  6. On rejection (rejection_feedback present): incorporate reviewer comment
     and regenerate — same milestone index, new artifact version.
  7. Clear rejection_feedback after processing.
"""

from __future__ import annotations

from app.agents.base import BaseAgent
from app.registry.loader import AgentLimits, AgentSpec
from app.sot.state import ApprovalStatus, ArchitectureSpec, CodeFile, MilestoneItem, ProjectState, TechStackSpec


def _make_default_spec() -> AgentSpec:
    return AgentSpec(
        name="MilestoneCodeAgent",
        role="engineer",
        description=(
            "Generates production code for one milestone at a time, "
            "writes files to disk, and raises a tech-lead review gate."
        ),
        allowed_tools=["write_file", "read_file"],
        limits=AgentLimits(max_steps=10, max_tool_calls=20, budget_usd=3.0),
    )


class MilestoneCodeAgent(BaseAgent):
    """Generates code for the current milestone and triggers a tech lead review."""

    def __init__(self, spec: AgentSpec | None = None) -> None:
        super().__init__(spec or _make_default_spec())

    # ── BaseAgent interface ────────────────────────────────────────────────────

    def run(self, state: ProjectState) -> dict:
        """Generate code for coding_plan[current_milestone_index]."""
        from app.services.llm_service import call_llm_json  # lazy

        idx = state.current_milestone_index
        plan = state.coding_plan
        if not plan or idx >= len(plan):
            return {}  # guard — nothing to do

        milestone = plan[idx]
        feedback_ctx = self._feedback_context(state, milestone.id)

        code_files = self._generate_code(state, milestone, call_llm_json, feedback_ctx)
        artifact_path = self._write_files(state.project_id, milestone, code_files)

        updated_plan = [m.model_dump() for m in plan]
        updated_plan[idx]["status"] = "in_progress"
        if artifact_path:
            updated_plan[idx]["code_artifact_path"] = artifact_path
        # Store structured file manifest
        if code_files:
            updated_plan[idx]["code_files"] = [
                CodeFile(
                    path=f["path"],
                    language=f.get("language", self._infer_language(f["path"])),
                    content=f["content"],
                    description=f.get("description", ""),
                ).model_dump()
                for f in code_files
            ]

        approval_key = f"milestone_{milestone.id}"
        approvals = {k: v.value for k, v in state.approvals_status.items()}
        approvals[approval_key] = ApprovalStatus.PENDING.value

        return {
            "current_phase": "milestone",
            "coding_plan": updated_plan,
            "approvals_status": approvals,
            "rejection_feedback": None,
        }

    # ── Private helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _feedback_context(state: ProjectState, milestone_id: str) -> str:
        fb = state.rejection_feedback
        if fb and fb.get("artifact_type") == f"milestone_{milestone_id}":
            comment = fb.get("comment", "").strip()
            if comment:
                return f"\n\nREJECTION FEEDBACK TO ADDRESS:\n{comment}"
        return ""

    def _generate_code(
        self,
        state: ProjectState,
        milestone: MilestoneItem,
        call_llm_json,
        feedback_ctx: str,
    ) -> list[dict]:
        """LLM: generate code files for this milestone."""
        tech_ctx = self._tech_stack_context(state.tech_stack)
        arch_ctx = self._architecture_context(state.architecture_spec, milestone)
        project_type = state.project_type or "generic"

        system = (
            "You are a senior software engineer implementing a milestone.\n\n"
            f"Project type: {project_type}\n"
            + tech_ctx
            + arch_ctx
            + "Return a JSON array of files to create. Each item:\n"
            '{"path": "relative/path/to/file.py", "language": "python", '
            '"content": "...", "description": "one-line description"}\n\n'
            "Write clean, production-quality code with docstrings. "
            "Follow the file structure defined in the architecture spec above. "
            "Only create files assigned to THIS milestone."
            + feedback_ctx
        )
        context = (
            f"Milestone: {milestone.name}\n"
            f"Description: {milestone.description}\n"
            f"Stories in scope: {', '.join(milestone.stories) or 'see requirements'}\n\n"
            f"Project Scope:\n{state.scope}\n\n"
            "Relevant requirements:\n"
            + "\n".join(f"- {r.text}" for r in state.requirements[:15])
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

    @staticmethod
    def _tech_stack_context(tech_stack: TechStackSpec | None) -> str:
        if not tech_stack:
            return ""
        parts = [f"  {k}: {v}" for k, v in tech_stack.model_dump().items() if v]
        if not parts:
            return ""
        return "Tech stack:\n" + "\n".join(parts) + "\n\n"

    @staticmethod
    def _architecture_context(
        arch_spec: ArchitectureSpec | None,
        milestone: MilestoneItem,
    ) -> str:
        if not arch_spec:
            return ""
        lines = [f"Architecture style: {arch_spec.style}"]
        files_for_milestone = arch_spec.milestone_file_map.get(milestone.name, [])
        if files_for_milestone:
            lines.append(f"Files for THIS milestone: {files_for_milestone}")
        else:
            lines.append(f"Full file tree (pick relevant files): {arch_spec.file_tree[:20]}")
        return "\n".join(lines) + "\n\n"

    @staticmethod
    def _infer_language(path: str) -> str:
        ext_map = {
            ".py": "python", ".ts": "typescript", ".tsx": "typescript",
            ".js": "javascript", ".jsx": "javascript", ".go": "go",
            ".yaml": "yaml", ".yml": "yaml", ".json": "json",
            ".md": "markdown", ".sh": "bash", ".dockerfile": "dockerfile",
        }
        for ext, lang in ext_map.items():
            if path.endswith(ext):
                return lang
        if "Dockerfile" in path:
            return "dockerfile"
        return "text"

    def _write_files(
        self,
        project_id: int,
        milestone: MilestoneItem,
        code_files: list[dict],
    ) -> str | None:
        """Write generated code files via the tool gateway."""
        if not code_files:
            return None

        base = f"storage/artifacts/{project_id}/code/{milestone.id}"
        written: list[str] = []
        for f in code_files:
            path = f"{base}/{f['path'].lstrip('/')}"
            result = self.call_tool("write_file", {"path": path, "content": f["content"]})
            if result.success:
                written.append(path)

        return base if written else None
