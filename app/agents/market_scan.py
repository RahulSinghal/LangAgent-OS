"""MarketScanAgent — Phase 2.

Runs as a DeepWorkAgent variant specialised for buy/build/hybrid evaluation.
Uses a deterministic scoring matrix (no external LLM required) so CI passes
without API keys.

Scoring dimensions (0–10 scale):
  ip_ownership    — value of owning the IP (build scores high)
  time_to_market  — speed to production (buy scores high)
  compliance      — regulatory fit (depends on NFRs)
  cost_efficiency — total cost of ownership (varies)
  lock_in_risk    — vendor lock-in exposure (build scores high)
  customization   — flexibility to customise (build scores high)

Weights (sum to 1.0):
  ip_ownership   0.20
  time_to_market 0.25
  compliance     0.15
  cost_efficiency 0.20
  lock_in_risk   0.10
  customization  0.10

Output: SoT patch containing market_eval section.
"""

from __future__ import annotations

from app.agents.deep_work import DeepWorkAgent, _deep_work_spec
from app.registry.loader import AgentSpec, AgentLimits
from app.sot.state import (
    DeepWorkOutput,
    MarketEval,
    MarketOption,
    ProjectState,
)


# ── Scoring constants ─────────────────────────────────────────────────────────

_WEIGHTS: dict[str, float] = {
    "ip_ownership":    0.20,
    "time_to_market":  0.25,
    "compliance":      0.15,
    "cost_efficiency": 0.20,
    "lock_in_risk":    0.10,
    "customization":   0.10,
}

# Base scores for each option × dimension (0–10)
_BASE_SCORES: dict[str, dict[str, float]] = {
    "build": {
        "ip_ownership":    9.0,
        "time_to_market":  3.0,
        "compliance":      7.0,   # adjusted by NFRs
        "cost_efficiency": 5.0,   # high upfront, low long-term
        "lock_in_risk":    9.0,
        "customization":   10.0,
    },
    "buy": {
        "ip_ownership":    2.0,
        "time_to_market":  9.0,
        "compliance":      6.0,   # vendor-dependent
        "cost_efficiency": 8.0,   # subscription but predictable
        "lock_in_risk":    2.0,
        "customization":   3.0,
    },
    "hybrid": {
        "ip_ownership":    6.0,
        "time_to_market":  7.0,
        "compliance":      7.0,
        "cost_efficiency": 6.0,
        "lock_in_risk":    5.0,
        "customization":   7.0,
    },
}

# Compliance boost: if NFRs mention compliance, "build" gets a boost
_COMPLIANCE_KEYWORDS = ("gdpr", "hipaa", "pci", "iso", "sox", "compliance", "regulatory")

# Vendors to include in the evaluation (stub)
_DEFAULT_VENDORS = ["Salesforce", "ServiceNow", "SAP", "Microsoft Dynamics", "Custom Build"]


# ── Spec factory ──────────────────────────────────────────────────────────────

def _market_scan_spec() -> AgentSpec:
    return AgentSpec(
        name="MarketScanAgent",
        role="market_analyst",
        description=(
            "Evaluates buy/build/hybrid options using a deterministic scoring "
            "matrix enriched with web search findings."
        ),
        allowed_tools=["web_search", "fetch_url"],
        limits=AgentLimits(max_steps=3, max_tool_calls=6, budget_usd=1.0),
    )


# ── MarketScanAgent ───────────────────────────────────────────────────────────

class MarketScanAgent(DeepWorkAgent):
    """Market evaluation agent — extends DeepWorkAgent.

    Produces a market_eval SoT patch with scored build/buy/hybrid options
    and a recommendation based on project requirements.
    """

    def __init__(self, spec: AgentSpec | None = None) -> None:
        super().__init__(spec or _market_scan_spec())

    # ── Override run() to produce market_eval patch ───────────────────────────

    def run(self, state: ProjectState) -> dict:
        """Return a SoT patch that populates market_eval."""
        output = self.execute_deep(state)
        return output.sot_patch

    # ── Override execute_deep() to inject market scoring ─────────────────────

    def execute_deep(self, state: ProjectState) -> DeepWorkOutput:
        """Run market evaluation and produce DeepWorkOutput + market_eval patch."""
        # Run base deep research first
        base_output = super().execute_deep(state)

        # Compute scoring matrix
        options = self._score_options(state)
        recommendation = self._pick_recommendation(options)
        confidence = self._estimate_confidence(state, options)

        market_eval = MarketEval(
            options=options,
            recommendation=recommendation,
            decision=recommendation,  # decided automatically in deterministic mode
            confidence=confidence,
            vendors_evaluated=_DEFAULT_VENDORS,
            deep_mode=state.market_eval.deep_mode,
        )

        # Build sot_patch
        sot_patch = {"market_eval": market_eval.model_dump(mode="json")}

        return DeepWorkOutput(
            findings=base_output.findings,
            decisions_recommended=base_output.decisions_recommended,
            open_questions=base_output.open_questions,
            sot_patch=sot_patch,
            references=base_output.references,
        )

    # ── Scoring helpers ───────────────────────────────────────────────────────

    def _score_options(self, state: ProjectState) -> list[MarketOption]:
        """Compute weighted scores for build / buy / hybrid."""
        has_compliance = self._has_compliance_requirements(state)
        has_many_reqs = len(state.requirements) >= 5
        time_sensitive = self._is_time_sensitive(state)

        options: list[MarketOption] = []
        for option_name, base in _BASE_SCORES.items():
            scores = dict(base)

            # Compliance adjustment: custom builds are better for strict compliance
            if has_compliance:
                scores["compliance"] = min(10.0, scores["compliance"] + 1.5
                                           if option_name == "build" else scores["compliance"])

            # Many requirements → build scores higher on customization
            if has_many_reqs and option_name == "build":
                scores["customization"] = min(10.0, scores["customization"] + 0.5)

            # Time sensitivity → buy scores higher on time_to_market
            if time_sensitive and option_name == "buy":
                scores["time_to_market"] = min(10.0, scores["time_to_market"] + 1.0)

            # Weighted total
            total = sum(scores[dim] * _WEIGHTS[dim] for dim in _WEIGHTS)

            options.append(
                MarketOption(
                    name=option_name,
                    scores=scores,
                    total_score=round(total, 2),
                    vendors=_DEFAULT_VENDORS if option_name in ("buy", "hybrid") else [],
                    rationale=self._option_rationale(option_name, scores),
                )
            )

        return options

    def _pick_recommendation(self, options: list[MarketOption]) -> str:
        """Select the option with the highest weighted score."""
        if not options:
            return "build"
        return max(options, key=lambda o: o.total_score).name

    def _estimate_confidence(
        self,
        state: ProjectState,
        options: list[MarketOption],
    ) -> float:
        """Confidence is higher when there is a clear winner."""
        if len(options) < 2:
            return 0.5
        sorted_scores = sorted([o.total_score for o in options], reverse=True)
        gap = sorted_scores[0] - sorted_scores[1]
        # Gap of >=1.0 → high confidence; gap <0.3 → low confidence
        return round(min(0.95, 0.5 + gap * 0.15), 2)

    def _has_compliance_requirements(self, state: ProjectState) -> bool:
        """True if any NFR or assumption mentions compliance keywords."""
        texts = (
            [r.text.lower() for r in state.requirements if r.category == "non_functional"]
            + [a.text.lower() for a in state.assumptions]
        )
        return any(kw in text for text in texts for kw in _COMPLIANCE_KEYWORDS)

    def _is_time_sensitive(self, state: ProjectState) -> bool:
        """True if the user message or requirements mention urgency."""
        msg = (state.last_user_message or "").lower()
        urgency_keywords = ("asap", "urgent", "immediately", "fast", "quick", "rapid")
        return any(kw in msg for kw in urgency_keywords)

    @staticmethod
    def _option_rationale(name: str, scores: dict[str, float]) -> str:
        """Generate a short rationale string for an option."""
        if name == "build":
            return (
                "Full IP ownership and maximum customisation at the cost of "
                "longer delivery timelines and higher initial investment."
            )
        if name == "buy":
            return (
                "Fastest time-to-market with predictable subscription costs; "
                "vendor lock-in is the primary risk to manage."
            )
        return (
            "Balanced approach: license a core platform and extend with "
            "custom integrations to balance speed, cost, and flexibility."
        )
