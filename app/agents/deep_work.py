"""DeepWorkAgent — Phase 2.

Bounded plan-act-observe loop with hard budgets:
  max_steps     — total observation rounds
  max_tool_calls — tool invocations across all rounds
  budget_usd    — cost ceiling (enforced by BaseAgent)

Execution model (deterministic in Phase 2, LLM-driven in Phase 3):
  1. plan()  — decide what to research based on SoT requirements / questions
  2. act()   — call tools (read-only: web_search, fetch_url, read_file)
  3. observe() — accumulate findings from tool results
  4. Repeat until budget exhausted or plan is done
  5. synthesize() — produce DeepWorkOutput with sot_patch

Policy toggle (deep_mode):
  "off"     — agent is disabled; no-op
  "suggest" — agent runs; sot_patch is advisory (caller decides whether to apply)
  "auto"    — sot_patch is applied automatically

Public API:
  DeepWorkAgent.execute_deep(state) -> DeepWorkOutput
"""

from __future__ import annotations

from app.agents.base import BaseAgent
from app.registry.loader import AgentSpec, AgentLimits
from app.sot.state import (
    DeepWorkDecision,
    DeepWorkFinding,
    DeepWorkOutput,
    ProjectState,
    QuestionItem,
)


# ── Spec factory (used when loading from registry is not yet wired) ───────────

def _deep_work_spec() -> AgentSpec:
    return AgentSpec(
        name="DeepWorkAgent",
        role="researcher",
        description=(
            "Bounded plan-act-observe research loop. Gathers findings "
            "from tools, produces structured DeepWorkOutput with sot_patch."
        ),
        allowed_tools=["web_search", "fetch_url", "read_file"],
        limits=AgentLimits(max_steps=5, max_tool_calls=10, budget_usd=2.0),
    )


# ── DeepWorkAgent ─────────────────────────────────────────────────────────────

class DeepWorkAgent(BaseAgent):
    """Plan-act-observe research agent with hard budgets.

    Phase 2: deterministic logic — no external LLM required.
    Simulate research by constructing findings from SoT requirements and
    using web_search stubs to discover vendor information.
    """

    def __init__(self, spec: AgentSpec | None = None) -> None:
        super().__init__(spec or _deep_work_spec())

    # ── BaseAgent interface ────────────────────────────────────────────────────

    def run(self, state: ProjectState) -> dict:
        """Run the plan-act-observe loop and return a minimal sot_patch.

        This is called by BaseAgent.execute() for SoT-patch mode.
        For full DeepWorkOutput use execute_deep() directly.
        """
        output = self.execute_deep(state)
        return output.sot_patch

    # ── Deep execution ────────────────────────────────────────────────────────

    def execute_deep(self, state: ProjectState) -> DeepWorkOutput:
        """Full research loop → DeepWorkOutput (not just a patch).

        Returns DeepWorkOutput regardless of deep_mode; the caller is
        responsible for checking deep_mode and deciding whether to apply
        the sot_patch.
        """
        findings: list[DeepWorkFinding] = []
        references: list[str] = []

        # ── Plan: derive research topics from SoT ─────────────────────────────
        topics = self._plan(state)

        # ── Act + Observe: bounded tool loop ──────────────────────────────────
        for topic in topics:
            if self._step_count >= self.spec.limits.max_steps:
                break
            self._step_count += 1

            result = self.call_tool("web_search", {"query": topic, "max_results": 2})
            if result.success and isinstance(result.output, list):
                for item in result.output:
                    findings.append(
                        DeepWorkFinding(
                            category="market",
                            finding=item.get("snippet", ""),
                            source=item.get("url", "web_search"),
                            confidence=0.7,
                        )
                    )
                    references.append(item.get("url", ""))

        # ── Synthesize: produce decisions and open questions ───────────────────
        decisions = self._synthesize_decisions(state, findings)
        open_qs = self._identify_open_questions(state, findings)

        return DeepWorkOutput(
            findings=findings,
            decisions_recommended=decisions,
            open_questions=open_qs,
            sot_patch={},   # DeepWorkAgent itself adds no SoT mutations by default
            references=[r for r in references if r],
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _plan(self, state: ProjectState) -> list[str]:
        """Derive research topics from the current SoT."""
        topics: list[str] = []

        # Research each requirement category
        categories = {r.category for r in state.requirements}
        for cat in sorted(categories):
            topics.append(f"{cat} software solutions")

        # If user described a domain, research it
        if state.last_user_message:
            words = state.last_user_message.split()[:5]
            topics.append(" ".join(words) + " vendor comparison")

        # Fallback
        if not topics:
            topics = ["enterprise software solutions"]

        return topics[: self.spec.limits.max_steps]

    def _synthesize_decisions(
        self,
        state: ProjectState,
        findings: list[DeepWorkFinding],
    ) -> list[DeepWorkDecision]:
        """Produce recommended decisions from findings."""
        decisions: list[DeepWorkDecision] = []

        if findings:
            decisions.append(
                DeepWorkDecision(
                    recommendation="Evaluate existing SaaS solutions before committing to build",
                    rationale=(
                        f"Research identified {len(findings)} relevant market signals "
                        "suggesting commercial options are worth evaluating."
                    ),
                    confidence=0.75,
                )
            )

        if any(r.category == "non_functional" for r in state.requirements):
            decisions.append(
                DeepWorkDecision(
                    recommendation="Validate NFRs against vendor SLAs",
                    rationale="Non-functional requirements found that may restrict vendor options.",
                    confidence=0.8,
                )
            )

        return decisions

    def _identify_open_questions(
        self,
        state: ProjectState,
        findings: list[DeepWorkFinding],
    ) -> list[str]:
        """Surface open questions based on research gaps."""
        questions: list[str] = []

        unanswered = [q.question for q in state.open_questions if not q.answered]
        questions.extend(unanswered[:3])

        if not any(r.category == "non_functional" for r in state.requirements):
            questions.append(
                "What are the non-functional requirements (performance, security, compliance)?"
            )

        return questions
