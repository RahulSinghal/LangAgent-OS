"""CodeReviewAgent — Step 4 (post-codegen, pre-approval).

Performs automated quality and security review of a generated milestone's code
before it reaches the human tech-lead gate.

Review dimensions:
  1. Security — OWASP Top 10, injection, hardcoded secrets, unsafe deserialization
  2. Code quality — naming, complexity, test coverage, docstrings
  3. Architecture — correct layer separation, no circular deps, follows file map
  4. Project-type specific — e.g. RAG chunking strategy, voice latency, CRM permissions

Output:
  - A structured review_feedback string stored on the MilestoneItem.
  - A severity score: "pass" | "warn" | "block".
  - If "block": sets milestone status back to "pending" so the human gate sees
    the CodeReviewAgent's findings alongside any human comments.
  - If "pass" or "warn": human gate still runs, but reviewer sees the findings.
"""

from __future__ import annotations

from app.agents.base import BaseAgent
from app.registry.loader import AgentLimits, AgentSpec
from app.sot.state import ApprovalStatus, MilestoneItem, ProjectState


# ── Project-type specific review checklists ────────────────────────────────────

_REVIEW_CHECKLISTS: dict[str, str] = {
    "rag_pipeline": (
        "RAG-specific checks:\n"
        "- Chunking strategy implemented correctly (no data loss at chunk boundaries)\n"
        "- Embedding calls are batched, not per-document individually\n"
        "- Vector store connection is pooled and error-handled\n"
        "- Retrieval results are deduped before passing to LLM\n"
        "- LLM prompt includes clear instruction to cite sources\n"
        "- No API keys hardcoded — must read from env"
    ),
    "web_app": (
        "Web app specific checks:\n"
        "- Auth middleware applied to all protected routes (no exposed admin endpoints)\n"
        "- CSRF protection enabled for state-changing operations\n"
        "- Input validation on all user-facing forms (server-side, not just client)\n"
        "- SQL queries use parameterised statements (no string concatenation)\n"
        "- CORS configured to allowed origins only (not *)\n"
        "- Sensitive fields excluded from API responses (passwords, tokens)"
    ),
    "crm": (
        "CRM specific checks:\n"
        "- Every data-access method checks org_id or tenant_id (no cross-tenant leakage)\n"
        "- Permission checks applied at service layer, not just route layer\n"
        "- Audit log entries written for all create/update/delete operations\n"
        "- Bulk operations have per-record error handling (one failure mustn't abort all)\n"
        "- Role assignments validated against org hierarchy (no privilege escalation)"
    ),
    "voice_chatbot": (
        "Voice chatbot specific checks:\n"
        "- Webhook endpoint validates telephony provider signature (HMAC or token)\n"
        "- TTS calls are async / non-blocking (latency must stay <500ms)\n"
        "- Dialogue state stored in Redis/DB (not in-memory — stateless across pods)\n"
        "- Fallback intent handler covers unrecognised inputs\n"
        "- Call recording compliance: consent collected before recording starts\n"
        "- Sensitive data (card numbers, PINs) masked in logs"
    ),
    "generic": (
        "General checks:\n"
        "- No hardcoded credentials or API keys\n"
        "- Input validation at system boundaries\n"
        "- Error handling does not expose stack traces to end users\n"
        "- Logging does not capture PII"
    ),
}


def _make_default_spec() -> AgentSpec:
    return AgentSpec(
        name="CodeReviewAgent",
        role="security_reviewer",
        description=(
            "Automated security and quality gate for generated milestone code. "
            "Runs before the human tech-lead approval gate."
        ),
        allowed_tools=["read_file"],
        limits=AgentLimits(max_steps=5, max_tool_calls=10, budget_usd=1.0),
    )


class CodeReviewAgent(BaseAgent):
    """Automated code review — security, quality, architecture, project-type checks."""

    def __init__(self, spec: AgentSpec | None = None) -> None:
        super().__init__(spec or _make_default_spec())

    # ── BaseAgent interface ────────────────────────────────────────────────────

    def run(self, state: ProjectState) -> dict:
        """Review the current milestone's code and store findings in SoT."""
        from app.services.llm_service import call_llm_json  # lazy

        idx = state.current_milestone_index
        plan = state.coding_plan
        if not plan or idx >= len(plan):
            return {}

        milestone = plan[idx]
        findings, severity = self._review_milestone(state, milestone, call_llm_json)

        updated_plan = [m.model_dump() for m in plan]
        updated_plan[idx]["review_feedback"] = findings

        # If the reviewer blocks the milestone, reset status so the tech-lead
        # gate sees "pending" with review findings prominently surfaced.
        if severity == "block":
            updated_plan[idx]["status"] = "pending"

        # Surface review in the approval map so the UI can show it
        approval_key = f"milestone_{milestone.id}_review"
        approvals = {k: v.value for k, v in state.approvals_status.items()}
        approvals[approval_key] = (
            ApprovalStatus.REJECTED.value if severity == "block"
            else ApprovalStatus.APPROVED.value
        )

        return {
            "coding_plan": updated_plan,
            "approvals_status": approvals,
        }

    # ── Private helpers ────────────────────────────────────────────────────────

    def _review_milestone(
        self,
        state: ProjectState,
        milestone: MilestoneItem,
        call_llm_json,
    ) -> tuple[str, str]:
        """LLM: review code files and return (findings_str, severity)."""
        project_type = state.project_type or "generic"
        checklist = _REVIEW_CHECKLISTS.get(project_type, _REVIEW_CHECKLISTS["generic"])

        # Read code files from disk if available, else use in-memory CodeFile list
        code_snippets = self._collect_code_snippets(state, milestone)

        system = (
            "You are a senior security and code quality reviewer.\n\n"
            "Review the provided code against these dimensions:\n"
            "1. Security (OWASP Top 10, secrets, injection)\n"
            "2. Code quality (naming, complexity, tests, docstrings)\n"
            "3. Architecture (layer separation, correct file structure)\n"
            f"4. {checklist}\n\n"
            "Return JSON:\n"
            "{\n"
            '  "severity": "pass" | "warn" | "block",\n'
            '  "summary": "one-line summary",\n'
            '  "findings": [\n'
            '    {"severity": "critical|warn|info", "file": "...", "issue": "...", "fix": "..."}\n'
            "  ]\n"
            "}\n\n"
            "severity rules:\n"
            "- 'block': any critical finding (hardcoded secret, SQL injection, auth bypass)\n"
            "- 'warn': warnings that should be fixed but do not block deployment\n"
            "- 'pass': no significant issues found"
        )
        context = (
            f"Milestone: {milestone.name}\n"
            f"Description: {milestone.description}\n\n"
            f"Code files:\n{code_snippets}"
        )
        try:
            result = call_llm_json(system, context)
            severity = result.get("severity", "warn")
            if severity not in ("pass", "warn", "block"):
                severity = "warn"
            findings_list = result.get("findings", [])
            summary = result.get("summary", "Review complete.")
            findings_lines = [f"**Review summary**: {summary}", f"**Severity**: {severity}"]
            for f in findings_list:
                sev = f.get("severity", "info").upper()
                file_ = f.get("file", "unknown")
                issue = f.get("issue", "")
                fix = f.get("fix", "")
                findings_lines.append(f"[{sev}] {file_}: {issue}" + (f" → {fix}" if fix else ""))
            return "\n".join(findings_lines), severity
        except Exception:
            return "Code review encountered an error — manual review required.", "warn"

    def _collect_code_snippets(
        self,
        state: ProjectState,
        milestone: MilestoneItem,
    ) -> str:
        """Collect code content from in-memory CodeFile list (truncated for token budget)."""
        if not milestone.code_files:
            # Try reading from disk artifact path
            if milestone.code_artifact_path:
                return f"[code at: {milestone.code_artifact_path}]"
            return "[no code files available]"

        snippets: list[str] = []
        total_chars = 0
        char_budget = 8000  # keep prompt manageable
        for cf in milestone.code_files:
            header = f"### {cf.path}\n"
            body = cf.content[:2000]  # cap per file
            snippet = header + body
            if total_chars + len(snippet) > char_budget:
                snippets.append(f"### {cf.path}\n[truncated — see artifact path]")
                break
            snippets.append(snippet)
            total_chars += len(snippet)
        return "\n\n".join(snippets)
