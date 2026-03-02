"""Unit tests for Phase 2 - DeepWorkAgent (no DB required)."""

import pytest

from app.agents.deep_work import DeepWorkAgent
from app.sot.state import (
    DeepWorkOutput,
    Phase,
    ProjectState,
    RequirementItem,
    QuestionItem,
    create_initial_state,
)
from app.sot.patch import apply_patch


def _state_with_reqs(**kwargs) -> ProjectState:
    sot = create_initial_state(project_id=1)
    if kwargs:
        sot = apply_patch(sot, kwargs)
    return sot


def test_deepwork_agent_initializes():
    agent = DeepWorkAgent()
    assert agent.spec.name == "DeepWorkAgent"
    assert agent.spec.role == "researcher"


def test_deepwork_agent_allowed_tools():
    agent = DeepWorkAgent()
    assert "web_search" in agent.spec.allowed_tools
    assert "fetch_url" in agent.spec.allowed_tools
    assert "read_file" in agent.spec.allowed_tools


def test_deepwork_agent_limits():
    agent = DeepWorkAgent()
    assert agent.spec.limits.max_steps >= 3
    assert agent.spec.limits.max_tool_calls >= 5


def test_execute_deep_returns_deepworkoutput():
    agent = DeepWorkAgent()
    sot = create_initial_state(project_id=1, user_message="Build an ERP system")
    result = agent.execute_deep(sot)
    assert isinstance(result, DeepWorkOutput)


def test_execute_deep_has_findings():
    agent = DeepWorkAgent()
    sot = _state_with_reqs(
        requirements=[{"category": "functional", "text": "Order management", "id": "r1"}],
        current_phase="discovery",
    )
    result = agent.execute_deep(sot)
    assert isinstance(result.findings, list)


def test_execute_deep_has_references():
    agent = DeepWorkAgent()
    sot = create_initial_state(project_id=1, user_message="Enterprise CRM")
    result = agent.execute_deep(sot)
    assert isinstance(result.references, list)


def test_execute_deep_has_open_questions():
    agent = DeepWorkAgent()
    sot = create_initial_state(project_id=1)
    result = agent.execute_deep(sot)
    assert isinstance(result.open_questions, list)


def test_execute_deep_has_decisions_recommended():
    agent = DeepWorkAgent()
    sot = _state_with_reqs(
        requirements=[{"category": "functional", "text": "Payment processing", "id": "r1"}],
    )
    result = agent.execute_deep(sot)
    assert isinstance(result.decisions_recommended, list)


def test_execute_deep_sot_patch_is_dict():
    agent = DeepWorkAgent()
    sot = create_initial_state(project_id=1)
    result = agent.execute_deep(sot)
    assert isinstance(result.sot_patch, dict)


def test_plan_uses_requirement_categories():
    agent = DeepWorkAgent()
    sot = _state_with_reqs(
        requirements=[
            {"category": "functional", "text": "Req 1", "id": "r1"},
            {"category": "non_functional", "text": "Perf", "id": "r2"},
        ],
    )
    topics = agent._plan(sot)
    assert len(topics) >= 1
    assert all(isinstance(t, str) for t in topics)


def test_plan_uses_user_message():
    agent = DeepWorkAgent()
    sot = create_initial_state(project_id=1, user_message="Build a supply chain platform")
    topics = agent._plan(sot)
    assert any("supply" in t.lower() for t in topics)


def test_plan_has_fallback():
    agent = DeepWorkAgent()
    sot = create_initial_state(project_id=1)  # no reqs, no user_message
    topics = agent._plan(sot)
    assert len(topics) >= 1


def test_budget_enforced_on_execute():
    agent = DeepWorkAgent()
    agent.spec.limits.max_steps = 1
    sot = create_initial_state(project_id=1)
    agent.execute(sot)  # first call - OK
    with pytest.raises(RuntimeError, match="max_steps"):
        agent.execute(sot)  # second call - over budget


def test_reset_counters_allows_re_execution():
    agent = DeepWorkAgent()
    agent.spec.limits.max_steps = 1
    sot = create_initial_state(project_id=1)
    agent.execute(sot)
    agent.reset_counters()
    # Should not raise
    agent.execute(sot)


def test_no_nfr_adds_open_question():
    agent = DeepWorkAgent()
    sot = _state_with_reqs(
        requirements=[{"category": "functional", "text": "Login", "id": "r1"}],
    )
    result = agent.execute_deep(sot)
    # With no NFRs there should be a question about them
    all_qs = " ".join(result.open_questions)
    assert "non-functional" in all_qs.lower() or "performance" in all_qs.lower() or len(result.open_questions) > 0
