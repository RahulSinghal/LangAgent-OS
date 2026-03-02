"""DiscoveryAgent — Phase 4.

Real LLM-driven discovery agent that replaces MockDiscoveryAgent.

Algorithm:
  1. If `last_user_message` is present: extract structured requirements via LLM
     (capture_answer), then rate completeness per category (update_coverage).
  2. Check discovery gate: all coverage_scores >= COVERAGE_THRESHOLD → done.
  3. Ask next question:
       a. Drain BRD/PRD/SOW gap `followup_questions` first (targeted gaps).
       b. When exhausted: ask LLM for one question about the weakest category.

The agent is stateless between calls — it reads state, returns a patch, and the
workflow node decides whether to pause or continue.
"""

from __future__ import annotations

import re
from typing import Any

from app.agents.base import BaseAgent
from app.registry.loader import AgentSpec, AgentLimits
from app.sot.state import ProjectState, QuestionItem, RequirementItem


# ── Constants ─────────────────────────────────────────────────────────────────

_COVERAGE_THRESHOLD: float = 0.7

_COVERAGE_CATEGORIES: list[str] = [
    "business_context",
    "users_and_scale",
    "functional_requirements",
    "non_functional_requirements",
    "technical_architecture",
    "technology_stack",
    "cloud_infrastructure",
    "security_architecture",
    "data_architecture",
    "integrations",
    "timeline_and_budget",
]

_NFR_RE = re.compile(
    r"\b(performance|security|availability|scalability|reliability|"
    r"uptime|latency|throughput|compliance|audit|backup)\b",
    re.IGNORECASE,
)
_INTEG_RE = re.compile(
    r"\b(api|integration|interface|connector|webhook|sync|feed|import|export)\b",
    re.IGNORECASE,
)


def _make_default_spec() -> AgentSpec:
    return AgentSpec(
        name="DiscoveryAgent",
        role="analyst",
        description="Coverage-score driven discovery with BRD/PRD/SOW gap analysis",
        allowed_tools=[],
        limits=AgentLimits(max_steps=50, max_tool_calls=0, budget_usd=2.0),
    )


# ── DiscoveryAgent ─────────────────────────────────────────────────────────────

class DiscoveryAgent(BaseAgent):
    """LLM-driven discovery: coverage-score questioning + gap follow-ups.

    Ported from Enterprise_bot/app/graph/nodes/discovery.py and adapted to the
    AgentOS BaseAgent + SoT-patch pattern.
    """

    def __init__(self, spec: AgentSpec | None = None) -> None:
        super().__init__(spec or _make_default_spec())

    # ── BaseAgent interface ────────────────────────────────────────────────────

    def run(self, state: ProjectState) -> dict:
        """Execute discovery logic and return a SoT patch dict.

        Returns:
            Patch dict with updated requirements, coverage_scores, followup_questions,
            open_questions, discovery_complete, and optionally last_user_message=None.
        """
        from app.services.llm_service import call_llm, call_llm_json  # lazy

        patch: dict[str, Any] = {}

        # ── Step 1: Extract requirements from the user's answer ────────────────
        if state.last_user_message and state.last_user_message.strip():
            gathered = self._capture_answer(state, call_llm_json)
            coverage = self._update_coverage(state, gathered, call_llm_json)
            patch["gathered_requirements"] = gathered
            patch["coverage_scores"] = coverage
            # Sync flat requirements list for other agents downstream
            new_flat = self._to_flat_requirements(gathered)
            patch["requirements"] = [r.model_dump() for r in state.requirements] + new_flat
            patch["last_user_message"] = None  # mark consumed

        # ── Step 2: Discovery gate check ──────────────────────────────────────
        scores = patch.get("coverage_scores") or state.coverage_scores
        if self._gate_passed(scores):
            patch["discovery_complete"] = True
            patch["current_phase"] = "discovery"
            return patch

        # ── Step 3: Formulate next question ───────────────────────────────────
        remaining = list(patch.get("followup_questions", state.followup_questions))

        if remaining:
            # Consume the first gap question
            question = remaining.pop(0)
            patch["followup_questions"] = remaining
        else:
            # Coverage-driven question about the weakest category
            question = self._ask_coverage_question(state, scores, call_llm)

        new_q = QuestionItem(question=question, category="discovery")
        patch["open_questions"] = (
            [q.model_dump() for q in state.open_questions] + [new_q.model_dump()]
        )
        patch["current_phase"] = "discovery"
        return patch

    # ── Private helpers ────────────────────────────────────────────────────────

    def _gate_passed(self, scores: dict[str, float]) -> bool:
        """Return True when ALL coverage categories are at or above the threshold."""
        if not scores:
            return False
        return all(
            scores.get(cat, 0.0) >= _COVERAGE_THRESHOLD
            for cat in _COVERAGE_CATEGORIES
        )

    def _capture_answer(self, state: ProjectState, call_llm_json) -> dict:
        """LLM: extract structured requirements from the client's latest answer."""
        system = (
            "You are a requirements extraction engine. "
            "Given the client's response during a discovery session, "
            "extract structured requirements organised by category.\n\n"
            "Current gathered requirements:\n" + str(state.gathered_requirements) + "\n\n"
            "Return JSON: "
            '{"updated_categories": {"category_name": {"field": "value"}}}\n'
            "Only include categories the message actually addresses. "
            'Return {"updated_categories": {}} if nothing extractable.'
        )
        try:
            result = call_llm_json(system, state.last_user_message or "")
            gathered = dict(state.gathered_requirements)
            for category, fields in result.get("updated_categories", {}).items():
                if isinstance(fields, dict):
                    cat_data = gathered.setdefault(category, {})
                    if isinstance(cat_data, dict):
                        cat_data.update({k: v for k, v in fields.items() if v})
                elif isinstance(fields, list):
                    existing = gathered.get(category, [])
                    if isinstance(existing, list):
                        gathered[category] = existing + fields
                    else:
                        gathered[category] = fields
            return gathered
        except Exception:
            return dict(state.gathered_requirements)

    def _update_coverage(
        self,
        state: ProjectState,
        gathered: dict,
        call_llm_json,
    ) -> dict[str, float]:
        """LLM: rate completeness of each discovery category 0.0 – 1.0."""
        system = (
            "You are a requirements completeness evaluator.\n\n"
            "0.0 = Nothing known\n"
            "0.3 = Briefly mentioned, lacks detail\n"
            "0.5 = Partially covered, some gaps\n"
            "0.7 = Well covered, minor gaps\n"
            "0.9 = Thoroughly covered\n"
            "1.0 = Complete, no gaps\n\n"
            "Return JSON with a score for every category:\n"
            '{"business_context": 0.0, "users_and_scale": 0.0, '
            '"functional_requirements": 0.0, "non_functional_requirements": 0.0, '
            '"technical_architecture": 0.0, "technology_stack": 0.0, '
            '"cloud_infrastructure": 0.0, "security_architecture": 0.0, '
            '"data_architecture": 0.0, "integrations": 0.0, '
            '"timeline_and_budget": 0.0}'
        )
        # Start from existing scores so we never go backwards on a category
        scores = dict(state.coverage_scores)
        try:
            result = call_llm_json(system, f"Requirements:\n{gathered}")
            for cat, score in result.items():
                if cat in _COVERAGE_CATEGORIES and isinstance(score, (int, float)):
                    scores[cat] = min(max(float(score), 0.0), 1.0)
        except Exception:
            pass
        return scores

    def _ask_coverage_question(
        self,
        state: ProjectState,
        scores: dict[str, float],
        call_llm,
    ) -> str:
        """LLM: ask ONE targeted question about the weakest coverage category."""
        # Find the category most in need of information
        weakest = (
            min(scores, key=lambda k: scores.get(k, 0.0))
            if scores
            else "business_context"
        )
        weakest_score = scores.get(weakest, 0.0)

        system = (
            f"You are a senior business analyst conducting a discovery session.\n"
            f"Domain: {state.domain}\n\n"
            f"Coverage scores (0.0=nothing known, 1.0=fully covered):\n{scores}\n\n"
            f"The weakest category is: {weakest} (score: {weakest_score})\n\n"
            f"Known so far:\n{state.gathered_requirements or 'Nothing yet.'}\n\n"
            "Rules:\n"
            "- Ask exactly ONE specific question about the weakest area\n"
            "- Reference what the client already told you if applicable\n"
            "- Professional but conversational tone\n"
            "- Do NOT start with 'Great', 'Thank you', or similar filler\n"
            "- Do NOT repeat a question already present in open_questions"
        )
        try:
            return call_llm(system, f"Ask one question about: {weakest}")
        except Exception:
            return (
                f"Can you tell me more about your "
                f"{weakest.replace('_', ' ')} requirements?"
            )

    def _to_flat_requirements(self, gathered: dict) -> list[dict]:
        """Convert structured gathered_requirements into flat RequirementItem dicts."""
        items: list[dict] = []
        for category, data in gathered.items():
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, str) and item.strip():
                        items.append({
                            "category": "functional",
                            "text": item.strip(),
                            "source": "discovery",
                            "priority": "medium",
                            "accepted": True,
                        })
            elif isinstance(data, dict):
                for key, val in data.items():
                    if isinstance(val, str) and val.strip():
                        cat = "non_functional" if _NFR_RE.search(val) else (
                            "integration" if _INTEG_RE.search(val) else "functional"
                        )
                        items.append({
                            "category": cat,
                            "text": f"{key}: {val}".strip(),
                            "source": "discovery",
                            "priority": "medium",
                            "accepted": True,
                        })
        return items
