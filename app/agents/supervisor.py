"""SupervisorAgent — Phase 1D.

Phase 1: deterministic rule-based team selection (no LLM call).
Phase 2: LLM-driven planning with DeepWork and Market agents.

Output: TaskDAG describing which agents run in what order.
The Supervisor does NOT mutate SoT state — it only produces the execution plan.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agents.base import BaseAgent
from app.registry.loader import AgentSpec, load_registry
from app.sot.state import Phase, ProjectState


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


# ── Phase → team mapping ──────────────────────────────────────────────────────

# Maps each workflow phase to: (list[agent_names], list[approval_types_needed])
_PHASE_PLAN: dict[Phase, tuple[list[str], list[str]]] = {
    Phase.INIT:        (["DiscoveryAgent"], []),
    Phase.DISCOVERY:   (["DiscoveryAgent"], []),
    Phase.PRD:         (["PRDAgent"],        ["prd"]),
    Phase.COMMERCIALS: (["PRDAgent"],        []),        # Phase 2: CommercialAgent
    Phase.SOW:         (["SOWAgent"],        ["sow"]),
    Phase.NEGOTIATION: (["SOWAgent"],        []),
    Phase.READINESS:   (["SOWAgent"],        []),        # Phase 2: ReadinessAgent
    Phase.COMPLETED:   ([],                  []),
}

_PHASE_GOALS: dict[Phase, dict[str, str]] = {
    Phase.INIT:        {"DiscoveryAgent": "Elicit initial requirements from the user"},
    Phase.DISCOVERY:   {"DiscoveryAgent": "Fill remaining requirement gaps"},
    Phase.PRD:         {"PRDAgent":       "Generate a structured PRD from requirements"},
    Phase.COMMERCIALS: {"PRDAgent":       "Confirm commercial scope"},
    Phase.SOW:         {"SOWAgent":       "Draft the Statement of Work"},
    Phase.NEGOTIATION: {"SOWAgent":       "Apply negotiated changes to SOW"},
    Phase.READINESS:   {"SOWAgent":       "Confirm client readiness checklist"},
    Phase.COMPLETED:   {},
}


# ── SupervisorAgent ───────────────────────────────────────────────────────────

class SupervisorAgent(BaseAgent):
    """Deterministic supervisor that builds a TaskDAG from phase rules.

    run() returns an empty patch — the Supervisor does not mutate SoT.
    Use plan() to obtain the TaskDAG.
    """

    def run(self, state: ProjectState) -> dict:
        """Supervisor does not mutate SoT state — returns empty patch."""
        return {}

    def plan(self, state: ProjectState) -> TaskDAG:
        """Build and return a TaskDAG for the current workflow phase.

        Args:
            state: Current Source of Truth.

        Returns:
            TaskDAG with team, tasks, approvals, and merge strategy.
        """
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
