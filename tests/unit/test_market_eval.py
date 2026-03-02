"""Unit tests for Phase 2 - MarketScanAgent and market_eval workflow node."""

import pytest

from app.agents.market_scan import MarketScanAgent
from app.sot.patch import apply_patch
from app.sot.state import (
    ApprovalStatus,
    MarketEval,
    MarketOption,
    Phase,
    ProjectState,
    create_initial_state,
)
from app.workflow.nodes.market_eval import market_eval_gate, market_eval_phase
from app.workflow.graph import WorkflowState


def _make_state(**patch_kwargs) -> WorkflowState:
    sot = create_initial_state(project_id=1)
    if patch_kwargs:
        sot = apply_patch(sot, patch_kwargs)
    return WorkflowState(
        sot=sot.model_dump_jsonb(),
        run_id=1,
        pause_reason=None,
        bot_response=None,
        approval_id=None,
    )


def test_market_scan_agent_initializes():
    agent = MarketScanAgent()
    assert agent.spec.name == "MarketScanAgent"
    assert agent.spec.role == "market_analyst"


def test_market_scan_agent_allowed_tools():
    agent = MarketScanAgent()
    assert "web_search" in agent.spec.allowed_tools


def test_score_options_returns_three_options():
    agent = MarketScanAgent()
    sot = create_initial_state(project_id=1)
    options = agent._score_options(sot)
    names = {o.name for o in options}
    assert names == {"build", "buy", "hybrid"}


def test_score_options_scores_in_range():
    agent = MarketScanAgent()
    sot = create_initial_state(project_id=1)
    options = agent._score_options(sot)
    for opt in options:
        for dim, score in opt.scores.items():
            assert 0.0 <= score <= 10.0, f"{opt.name}.{dim} = {score} out of range"
        assert 0.0 <= opt.total_score <= 10.0


def test_compliance_nfr_boosts_build_score():
    agent = MarketScanAgent()
    sot_plain = create_initial_state(project_id=1)
    sot_compliance = apply_patch(sot_plain, {
        "requirements": [{"category": "non_functional", "text": "GDPR compliance required", "id": "r1"}],
    })
    opts_plain = agent._score_options(sot_plain)
    opts_compliance = agent._score_options(sot_compliance)

    build_plain = next(o for o in opts_plain if o.name == "build")
    build_comp = next(o for o in opts_compliance if o.name == "build")
    assert build_comp.scores["compliance"] >= build_plain.scores["compliance"]


def test_pick_recommendation_returns_valid_option():
    agent = MarketScanAgent()
    sot = create_initial_state(project_id=1)
    options = agent._score_options(sot)
    rec = agent._pick_recommendation(options)
    assert rec in ("build", "buy", "hybrid")


def test_pick_recommendation_picks_highest_score():
    agent = MarketScanAgent()
    options = [
        MarketOption(name="build", total_score=7.5),
        MarketOption(name="buy",   total_score=6.2),
        MarketOption(name="hybrid",total_score=6.8),
    ]
    assert agent._pick_recommendation(options) == "build"


def test_confidence_is_between_0_and_1():
    agent = MarketScanAgent()
    sot = create_initial_state(project_id=1)
    options = agent._score_options(sot)
    conf = agent._estimate_confidence(sot, options)
    assert 0.0 <= conf <= 1.0


def test_execute_deep_produces_market_eval_patch():
    agent = MarketScanAgent()
    sot = create_initial_state(project_id=1, user_message="Analytics platform")
    output = agent.execute_deep(sot)
    assert "market_eval" in output.sot_patch
    me = output.sot_patch["market_eval"]
    assert "recommendation" in me
    assert me["recommendation"] in ("build", "buy", "hybrid")


def test_market_eval_options_in_patch():
    agent = MarketScanAgent()
    sot = create_initial_state(project_id=1)
    output = agent.execute_deep(sot)
    me = output.sot_patch["market_eval"]
    assert len(me["options"]) == 3


def test_market_eval_phase_sets_phase():
    state = _make_state(current_phase="discovery")
    result = market_eval_phase(state)
    sot = ProjectState(**result["sot"])
    assert sot.current_phase == Phase.MARKET_EVAL


def test_market_eval_phase_populates_market_eval():
    state = _make_state(current_phase="discovery")
    result = market_eval_phase(state)
    sot = ProjectState(**result["sot"])
    assert sot.market_eval.recommendation in ("build", "buy", "hybrid")


def test_market_eval_phase_no_pause():
    state = _make_state(current_phase="discovery")
    result = market_eval_phase(state)
    assert result["pause_reason"] is None


def test_gate_build_decision_does_not_pause():
    me = MarketEval(recommendation="build", decision="build", deep_mode="suggest")
    state = _make_state(
        current_phase="market_eval",
        market_eval=me.model_dump(mode="json"),
    )
    result = market_eval_gate(state)
    assert result["pause_reason"] is None


def test_gate_buy_decision_pauses():
    me = MarketEval(recommendation="buy", decision="buy", deep_mode="suggest")
    state = _make_state(
        current_phase="market_eval",
        market_eval=me.model_dump(mode="json"),
    )
    result = market_eval_gate(state)
    assert result["pause_reason"] == "waiting_approval"


def test_gate_hybrid_decision_pauses():
    me = MarketEval(recommendation="hybrid", decision="hybrid", deep_mode="suggest")
    state = _make_state(
        current_phase="market_eval",
        market_eval=me.model_dump(mode="json"),
    )
    result = market_eval_gate(state)
    assert result["pause_reason"] == "waiting_approval"


def test_gate_auto_mode_never_pauses():
    me = MarketEval(recommendation="buy", decision="buy", deep_mode="auto")
    state = _make_state(
        current_phase="market_eval",
        market_eval=me.model_dump(mode="json"),
    )
    result = market_eval_gate(state)
    assert result["pause_reason"] is None


def test_gate_already_approved_continues():
    me = MarketEval(recommendation="buy", decision="buy", deep_mode="suggest")
    state = _make_state(
        current_phase="market_eval",
        market_eval=me.model_dump(mode="json"),
        approvals_status={"market_eval": "approved"},
    )
    result = market_eval_gate(state)
    assert result["pause_reason"] is None


def test_gate_buy_sets_pending_approval():
    me = MarketEval(recommendation="buy", decision="buy", deep_mode="suggest")
    state = _make_state(
        current_phase="market_eval",
        market_eval=me.model_dump(mode="json"),
    )
    result = market_eval_gate(state)
    sot = ProjectState(**result["sot"])
    assert sot.approvals_status.get("market_eval") == ApprovalStatus.PENDING


def test_gate_buy_includes_bot_response():
    me = MarketEval(recommendation="buy", decision="buy", deep_mode="suggest")
    state = _make_state(
        current_phase="market_eval",
        market_eval=me.model_dump(mode="json"),
    )
    result = market_eval_gate(state)
    assert result.get("bot_response") is not None
    assert "BUY" in result["bot_response"].upper()
