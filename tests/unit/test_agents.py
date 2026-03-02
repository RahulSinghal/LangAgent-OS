"""Unit tests for Phase 1D — registry, gateway, BaseAgent, Supervisor, mocks."""

import pytest

from app.agents.mock_agents import MockDiscoveryAgent, MockPRDAgent, MockSOWAgent
from app.agents.supervisor import SupervisorAgent, TaskDAG
from app.registry.loader import AgentLimits, AgentSpec, get_agent_spec, load_registry
from app.sot.state import ApprovalStatus, Phase, create_initial_state
from app.tools.gateway import ToolResult, execute as gateway_execute


# ── Registry loader ───────────────────────────────────────────────────────────

def test_load_registry_returns_dict():
    registry = load_registry()
    assert isinstance(registry, dict)
    assert len(registry) >= 4  # SupervisorAgent, DiscoveryAgent, PRDAgent, SOWAgent


def test_load_registry_has_supervisor():
    registry = load_registry()
    assert "SupervisorAgent" in registry


def test_load_registry_agent_spec_fields():
    registry = load_registry()
    spec = registry["DiscoveryAgent"]
    assert spec.role == "analyst"
    assert "requirements_elicitation" in spec.capabilities
    assert spec.limits.max_steps > 0


def test_get_agent_spec_valid():
    spec = get_agent_spec("PRDAgent")
    assert spec.name == "PRDAgent"
    assert spec.role == "product_manager"


def test_get_agent_spec_invalid_raises():
    with pytest.raises(KeyError, match="not found"):
        get_agent_spec("NonExistentAgent")


def test_agent_spec_defaults():
    spec = AgentSpec(name="TestAgent", role="tester", description="test")
    assert spec.allowed_tools == []
    assert spec.capabilities == []
    assert isinstance(spec.limits, AgentLimits)


# ── Tool Gateway ──────────────────────────────────────────────────────────────

def test_gateway_unknown_tool():
    result = gateway_execute("totally_unknown_tool", {})
    assert result.success is False
    assert "Unknown tool" in result.error


def test_gateway_allowlist_blocks():
    result = gateway_execute(
        tool_name="read_file",
        payload={"path": "/tmp/x"},
        agent_name="TestAgent",
        allowed_tools=[],  # empty allowlist — should block
    )
    assert result.success is False
    assert "not in allowlist" in result.error


def test_gateway_allowlist_permits():
    import tempfile, os
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("hello")
        tmp = f.name
    try:
        result = gateway_execute(
            tool_name="read_file",
            payload={"path": tmp},
            agent_name="TestAgent",
            allowed_tools=["read_file"],
        )
        assert result.success is True
        assert result.output == "hello"
    finally:
        os.unlink(tmp)


def test_gateway_dry_run():
    result = gateway_execute(
        tool_name="write_file",
        payload={"path": "/tmp/test.txt", "content": "hi"},
        dry_run=True,
    )
    assert result.success is True
    assert result.output["dry_run"] is True


def test_gateway_no_allowlist_permits_all():
    import tempfile, os
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("data")
        tmp = f.name
    try:
        result = gateway_execute("read_file", {"path": tmp})
        assert result.success is True
    finally:
        os.unlink(tmp)


# ── MockDiscoveryAgent ────────────────────────────────────────────────────────

def test_mock_discovery_agent_run():
    agent = MockDiscoveryAgent()
    state = create_initial_state(project_id=1)
    new_state = agent.execute(state)

    assert new_state.current_phase == Phase.DISCOVERY
    assert len(new_state.open_questions) == 1
    assert new_state.open_questions[0].question == "What is the primary use case?"
    assert len(new_state.requirements) == 1
    assert new_state.requirements[0].category == "functional"


def test_mock_discovery_agent_appends():
    """Running discovery twice accumulates questions/requirements."""
    agent = MockDiscoveryAgent()
    state = create_initial_state(project_id=1)
    state1 = agent.execute(state)
    agent.reset_counters()
    state2 = agent.execute(state1)

    assert len(state2.open_questions) == 2
    assert len(state2.requirements) == 2


# ── MockPRDAgent ──────────────────────────────────────────────────────────────

def test_mock_prd_agent_run():
    agent = MockPRDAgent()
    state = create_initial_state(project_id=1)
    new_state = agent.execute(state)

    assert new_state.current_phase == Phase.PRD
    assert new_state.approvals_status.get("prd") == ApprovalStatus.PENDING


# ── MockSOWAgent ──────────────────────────────────────────────────────────────

def test_mock_sow_agent_run():
    agent = MockSOWAgent()
    state = create_initial_state(project_id=1)
    new_state = agent.execute(state)

    assert new_state.current_phase == Phase.SOW
    assert new_state.approvals_status.get("sow") == ApprovalStatus.PENDING


# ── BaseAgent budget enforcement ──────────────────────────────────────────────

def test_agent_step_budget_exceeded():
    agent = MockDiscoveryAgent()
    agent.spec.limits.max_steps = 1  # exhaust budget immediately
    state = create_initial_state(project_id=1)

    agent.execute(state)  # first call consumes the budget
    with pytest.raises(RuntimeError, match="max_steps"):
        agent.execute(state)


def test_agent_tool_budget_exceeded():
    agent = MockDiscoveryAgent()
    agent.spec.limits.max_tool_calls = 0  # zero tool budget
    result = agent.call_tool("read_file", {"path": "/tmp/x"})
    assert result.success is False
    assert "max_tool_calls" in result.error


# ── SupervisorAgent ───────────────────────────────────────────────────────────

def test_supervisor_plan_init_phase():
    spec = get_agent_spec("SupervisorAgent")
    supervisor = SupervisorAgent(spec)
    state = create_initial_state(project_id=1)

    dag = supervisor.plan(state)

    assert isinstance(dag, TaskDAG)
    assert len(dag.tasks) == 1
    assert dag.tasks[0].agent_name == "DiscoveryAgent"
    assert dag.approvals_needed == []


def test_supervisor_plan_prd_phase():
    spec = get_agent_spec("SupervisorAgent")
    supervisor = SupervisorAgent(spec)
    from app.sot.patch import apply_patch
    state = apply_patch(create_initial_state(project_id=1), {"current_phase": "prd"})

    dag = supervisor.plan(state)

    assert dag.tasks[0].agent_name == "PRDAgent"
    assert "prd" in dag.approvals_needed


def test_supervisor_plan_sow_phase():
    spec = get_agent_spec("SupervisorAgent")
    supervisor = SupervisorAgent(spec)
    from app.sot.patch import apply_patch
    state = apply_patch(create_initial_state(project_id=1), {"current_phase": "sow"})

    dag = supervisor.plan(state)

    assert dag.tasks[0].agent_name == "SOWAgent"
    assert "sow" in dag.approvals_needed


def test_supervisor_plan_completed_phase():
    spec = get_agent_spec("SupervisorAgent")
    supervisor = SupervisorAgent(spec)
    from app.sot.patch import apply_patch
    state = apply_patch(create_initial_state(project_id=1), {"current_phase": "completed"})

    dag = supervisor.plan(state)

    assert dag.tasks == []
    assert dag.team == []


def test_supervisor_run_returns_empty_patch():
    """Supervisor.run() should not mutate SoT."""
    spec = get_agent_spec("SupervisorAgent")
    supervisor = SupervisorAgent(spec)
    state = create_initial_state(project_id=1)
    new_state = supervisor.execute(state)
    assert new_state.current_phase == state.current_phase


def test_supervisor_dag_sequential_tasks_have_dependencies():
    """In sequential mode, task N+1 depends on task N."""
    spec = get_agent_spec("SupervisorAgent")
    supervisor = SupervisorAgent(spec)
    state = create_initial_state(project_id=1)
    dag = supervisor.plan(state)

    for i, task in enumerate(dag.tasks[1:], start=1):
        assert dag.tasks[i - 1].id in task.depends_on
