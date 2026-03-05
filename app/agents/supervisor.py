"""SupervisorAgent — Phase 1D / Phase 5.

Phase 1: deterministic rule-based team selection (no LLM call).
Phase 5: LLM-driven planning — the LLM reads the SoT and the agent registry
         and returns a context-aware TaskDAG.  Falls back to the deterministic
         plan if the LLM call fails or returns invalid agent names.

SUPERVISOR_MODE (config):
  "deterministic" — always use _PHASE_PLAN (default, zero LLM cost)
  "llm"           — try plan_llm(); fall back to deterministic on any error

Output: TaskDAG describing which agents run in what order.
The Supervisor does NOT mutate SoT state — it only produces the execution plan.
"""

from __future__ import annotations

import json

import structlog

from pydantic import BaseModel, Field

from app.agents.base import BaseAgent
from app.registry.loader import AgentLimits, AgentSpec, load_registry
from app.sot.state import Phase, ProjectState


def _make_default_spec() -> AgentSpec:
    return AgentSpec(
        name="SupervisorAgent",
        role="supervisor",
        description="Plans and coordinates agent execution per workflow phase",
        allowed_tools=[],
        limits=AgentLimits(max_steps=3, max_tool_calls=0, budget_usd=0.5),
    )

logger = structlog.get_logger(__name__)


# ── TaskDAG schema ────────────────────────────────────────────────────────────

class TeamMember(BaseModel):
    role: str
    agent_name: str


class TaskItem(BaseModel):
    id: str
    agent_name: str
    goal: str
    depends_on: list[str] = Field(default_factory=list)


class TaskDAG(BaseModel):
    """Execution plan produced by the Supervisor for one workflow phase."""
    team: list[TeamMember]
    tasks: list[TaskItem]
    merge_strategy: str = "sequential"   # "sequential" | "parallel_then_merge"
    approvals_needed: list[str] = Field(default_factory=list)
    rationale: str = ""


# ── Phase → team mapping (deterministic fallback) ─────────────────────────────

# Maps each workflow phase to: (list[agent_names], list[approval_types_needed])
_PHASE_PLAN: dict[Phase, tuple[list[str], list[str]]] = {
    Phase.INIT:        (["DiscoveryAgent"],     []),
    Phase.DISCOVERY:   (["DiscoveryAgent"],     []),
    Phase.MARKET_EVAL: (["MarketScanAgent"],    ["market_eval"]),
    Phase.PRD:         (["PRDAgent"],           ["prd"]),
    Phase.COMMERCIALS: (["CommercialAgent"],    ["commercials"]),
    Phase.SOW:         (["SOWAgent"],           ["sow"]),
    Phase.NEGOTIATION: (["SOWAgent"],           []),
    Phase.CODING:      (["CodingPlanAgent"],    ["coding_plan"]),
    Phase.MILESTONE:   (["MilestoneCodeAgent"], []),
    Phase.READINESS:   (["ReadinessAgent"],     ["readiness"]),
    Phase.COMPLETED:   ([],                     []),
}

_PHASE_GOALS: dict[Phase, dict[str, str]] = {
    Phase.INIT:        {"DiscoveryAgent":     "Elicit initial requirements from the user"},
    Phase.DISCOVERY:   {"DiscoveryAgent":     "Fill remaining requirement gaps"},
    Phase.MARKET_EVAL: {"MarketScanAgent":    "Score build/buy/hybrid options and recommend"},
    Phase.PRD:         {"PRDAgent":           "Generate a structured PRD from requirements"},
    Phase.COMMERCIALS: {"CommercialAgent":    "Generate commercial proposal with pricing and milestones"},
    Phase.SOW:         {"SOWAgent":           "Draft the Statement of Work"},
    Phase.NEGOTIATION: {"SOWAgent":           "Apply negotiated changes to SOW"},
    Phase.CODING:      {"CodingPlanAgent":    "Divide backlog into coding milestones for tech-lead sign-off"},
    Phase.MILESTONE:   {"MilestoneCodeAgent": "Generate production-quality code for the current milestone"},
    Phase.READINESS:   {"ReadinessAgent":     "Generate deployment readiness checklist and collect infra prefs"},
    Phase.COMPLETED:   {},
}


# ── SupervisorAgent ───────────────────────────────────────────────────────────

class SupervisorAgent(BaseAgent):
    """Supervisor that builds a TaskDAG — deterministic or LLM-driven.

    run() returns an empty patch — the Supervisor does not mutate SoT.
    Use plan() to obtain the TaskDAG.
    """

    def __init__(self, spec: AgentSpec | None = None) -> None:
        super().__init__(spec or _make_default_spec())

    def run(self, state: ProjectState) -> dict:
        """Supervisor does not mutate SoT state — returns empty patch."""
        return {}

    def plan(self, state: ProjectState) -> TaskDAG:
        """Build and return a TaskDAG for the current workflow phase.

        Delegates to plan_llm() when SUPERVISOR_MODE == "llm"; always falls
        back to the deterministic plan on any error.
        """
        from app.core.config import settings
        if settings.SUPERVISOR_MODE == "llm" and not _is_mock_mode():
            try:
                dag = self.plan_llm(state)
                if dag:
                    logger.info("supervisor.llm_plan", phase=state.current_phase.value)
                    return dag
            except Exception as exc:
                logger.warning("supervisor.llm_plan_failed", error=str(exc))
        return self._plan_deterministic(state)

    def plan_llm(self, state: ProjectState) -> TaskDAG | None:
        """LLM-driven planning: the model reads the SoT summary and the agent
        registry and returns a context-aware TaskDAG.

        The LLM output is validated against the registry — any agent name not
        in the registry causes a fallback to the deterministic plan.

        Returns:
            TaskDAG if the LLM produced a valid plan, None to trigger fallback.
        """
        from app.services.llm_service import call_llm_json  # lazy

        registry = load_registry()
        valid_names = sorted(registry.keys())
        sot_summary = _sot_summary(state)

        system = (
            "You are a project supervisor at a consulting firm. "
            "Select the right agents and write context-specific goals "
            "for the current workflow phase.\n\n"
            f"Current phase: {state.current_phase.value}\n"
            f"Domain: {state.domain}\n"
            f"Available agents: {json.dumps(valid_names)}\n\n"
            "Return JSON:\n"
            "{\n"
            '  "tasks": [\n'
            '    {"agent_name": "AgentName", "goal": "specific goal for this project", '
            '"depends_on": []}\n'
            "  ],\n"
            '  "merge_strategy": "sequential",\n'
            '  "approvals_needed": ["artifact_type", ...],\n'
            '  "rationale": "one sentence"\n'
            "}\n\n"
            "Rules:\n"
            "- ONLY use agent names from the Available agents list.\n"
            "- Write goals specific to this project, not generic descriptions.\n"
            "- Prefer 1-2 agents per phase. Use parallel_then_merge only when "
            "agents can genuinely work independently and their outputs must be merged.\n"
            "- approvals_needed lists artifact types requiring human sign-off "
            "before the next phase begins."
        )

        result = call_llm_json(system, f"Project context:\n{sot_summary}")
        if not isinstance(result, dict) or "tasks" not in result:
            return None

        raw_tasks = result.get("tasks", [])
        if not raw_tasks:
            return None

        # Validate all agent names against registry — reject on any unknown name
        for t in raw_tasks:
            if t.get("agent_name") not in registry:
                logger.warning(
                    "supervisor.unknown_agent",
                    agent=t.get("agent_name"),
                    valid=valid_names,
                )
                return None

        # Build validated TaskDAG
        team: list[TeamMember] = []
        tasks: list[TaskItem] = []
        seen: set[str] = set()

        for i, t in enumerate(raw_tasks):
            name = t["agent_name"]
            if name not in seen:
                spec = registry[name]
                team.append(TeamMember(role=spec.role, agent_name=name))
                seen.add(name)

            task_id = f"task_{i + 1}"
            depends_on = [f"task_{j}" for j in t.get("depends_on", [])]
            tasks.append(TaskItem(
                id=task_id,
                agent_name=name,
                goal=str(t.get("goal", f"Execute {name}")),
                depends_on=depends_on,
            ))

        return TaskDAG(
            team=team,
            tasks=tasks,
            merge_strategy=result.get("merge_strategy", "sequential"),
            approvals_needed=result.get("approvals_needed", []),
            rationale=result.get("rationale", "LLM-generated plan"),
        )

    # ── Private ───────────────────────────────────────────────────────────────

    def _plan_deterministic(self, state: ProjectState) -> TaskDAG:
        """Build a TaskDAG from the static _PHASE_PLAN lookup."""
        phase = state.current_phase
        agent_names, approvals = _PHASE_PLAN.get(phase, ([], []))
        goals = _PHASE_GOALS.get(phase, {})
        registry = load_registry()

        team: list[TeamMember] = []
        tasks: list[TaskItem] = []

        for i, name in enumerate(agent_names):
            spec = registry.get(name)
            role = spec.role if spec else "unknown"
            team.append(TeamMember(role=role, agent_name=name))

            task_id = f"task_{i + 1}"
            depends_on = [f"task_{i}"] if i > 0 else []
            tasks.append(
                TaskItem(
                    id=task_id,
                    agent_name=name,
                    goal=goals.get(name, f"Execute {name}"),
                    depends_on=depends_on,
                )
            )

        rationale = (
            f"Phase '{phase.value}': assigned {len(agent_names)} agent(s). "
            f"Approvals required: {approvals or 'none'}."
        )

        return TaskDAG(
            team=team,
            tasks=tasks,
            merge_strategy="sequential",
            approvals_needed=approvals,
            rationale=rationale,
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sot_summary(state: ProjectState) -> str:
    """Compact SoT digest for the LLM Supervisor prompt (keeps token count low)."""
    req_sample = [r.text for r in state.requirements[:8]]
    return (
        f"phase={state.current_phase.value} domain={state.domain}\n"
        f"requirements ({len(state.requirements)} total, sample): {req_sample}\n"
        f"scope_summary: {(state.scope or {}).get('summary', 'not yet generated')}\n"
        f"hosting_preference: {state.hosting_preference}\n"
        f"discovery_complete: {state.discovery_complete}\n"
        f"milestones_count: {len(state.coding_plan)}\n"
        f"current_milestone_index: {state.current_milestone_index}"
    )


def _is_mock_mode() -> bool:
    try:
        from app.core.runtime import use_mock_agents
        return use_mock_agents()
    except Exception:
        return False
