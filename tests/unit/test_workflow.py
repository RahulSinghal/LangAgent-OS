"""Unit tests for Phase 1E — workflow nodes and graph routing (no DB required)."""

import pytest

from app.core.config import settings
from app.sot.patch import apply_patch
from app.sot.state import ApprovalStatus, Phase, create_initial_state
from app.workflow.graph import WorkflowState, _route_entry, get_workflow
from app.workflow.nodes.approval_gate import prd_approval_gate, sow_approval_gate
from app.workflow.nodes.discovery import discovery_loop
from app.workflow.nodes.end import end_node
from app.workflow.nodes.intake import intake_normalize
from app.workflow.nodes.prd import prd_phase
from app.workflow.nodes.sow import sow_phase


# ── Helper ────────────────────────────────────────────────────────────────────

def _make_state(project_id: int = 1, **patch_kwargs) -> WorkflowState:
    sot = create_initial_state(project_id=project_id)
    if patch_kwargs:
        sot = apply_patch(sot, patch_kwargs)
    return WorkflowState(
        sot=sot.model_dump_jsonb(),
        run_id=1,
        pause_reason=None,
        bot_response=None,
        approval_id=None,
    )


# ── Entry router ──────────────────────────────────────────────────────────────

def test_route_entry_init_goes_to_intake():
    state = _make_state(current_phase="init")
    assert _route_entry(state) == "intake"


def test_route_entry_discovery_goes_to_discovery():
    state = _make_state(current_phase="discovery")
    assert _route_entry(state) == "discovery"


def test_route_entry_prd_goes_to_prd_gate():
    state = _make_state(current_phase="prd")
    assert _route_entry(state) == "prd_gate"


def test_route_entry_sow_goes_to_sow_gate():
    state = _make_state(current_phase="sow")
    assert _route_entry(state) == "sow_gate"


def test_route_entry_completed_goes_to_end():
    state = _make_state(current_phase="completed")
    assert _route_entry(state) == "end"


# ── intake_normalize ──────────────────────────────────────────────────────────

def test_intake_sets_phase_to_discovery():
    state = _make_state()
    result = intake_normalize(state)
    from app.sot.state import ProjectState
    sot = ProjectState(**result["sot"])
    assert sot.current_phase == Phase.DISCOVERY


def test_intake_clears_pause_reason():
    state = _make_state()
    state["pause_reason"] = "waiting_user"
    result = intake_normalize(state)
    assert result["pause_reason"] is None


# ── discovery_loop ────────────────────────────────────────────────────────────

def test_discovery_first_call_pauses():
    settings.USE_MOCK_AGENTS = True
    state = _make_state(current_phase="discovery")
    result = discovery_loop(state)
    assert result["pause_reason"] == "waiting_user"
    assert result["bot_response"] is not None


def test_discovery_sets_bot_response():
    settings.USE_MOCK_AGENTS = True
    state = _make_state(current_phase="discovery")
    result = discovery_loop(state)
    assert isinstance(result["bot_response"], str)
    assert len(result["bot_response"]) > 0


def test_discovery_second_call_continues():
    """Mock discovery completes when last_user_message is present and a prior question exists."""
    settings.USE_MOCK_AGENTS = True
    # Mock agent's "second call" heuristic requires at least one existing open question.
    state = _make_state(
        current_phase="discovery",
        last_user_message="Answer",
        open_questions=[{"question": "What is the primary use case?", "category": "scope", "answered": False}],
    )
    result = discovery_loop(state)
    assert result["pause_reason"] is None
    assert result["bot_response"] is None


def test_discovery_updates_sot():
    settings.USE_MOCK_AGENTS = True
    state = _make_state(current_phase="discovery")
    result = discovery_loop(state)
    from app.sot.state import ProjectState
    sot = ProjectState(**result["sot"])
    assert len(sot.requirements) >= 1


# ── prd_phase ─────────────────────────────────────────────────────────────────

def test_prd_phase_sets_phase():
    settings.USE_MOCK_AGENTS = True
    state = _make_state(current_phase="discovery")
    result = prd_phase(state)
    from app.sot.state import ProjectState
    sot = ProjectState(**result["sot"])
    assert sot.current_phase == Phase.PRD


def test_prd_phase_sets_approval_pending():
    settings.USE_MOCK_AGENTS = True
    state = _make_state(current_phase="discovery")
    result = prd_phase(state)
    from app.sot.state import ProjectState
    sot = ProjectState(**result["sot"])
    assert sot.approvals_status.get("prd") == ApprovalStatus.PENDING
    # Default hosting_preference is client → requires client server details approval too
    assert sot.approvals_status.get("server_details_client") == ApprovalStatus.PENDING


def test_prd_phase_no_pause():
    settings.USE_MOCK_AGENTS = True
    state = _make_state()
    result = prd_phase(state)
    assert result["pause_reason"] is None


# ── prd_approval_gate ─────────────────────────────────────────────────────────

def test_prd_gate_pending_pauses():
    state = _make_state(
        current_phase="prd",
        approvals_status={"prd": "pending", "server_details_client": "pending"},
    )
    result = prd_approval_gate(state)
    assert result["pause_reason"] == "waiting_approval"


def test_prd_gate_approved_continues():
    state = _make_state(
        current_phase="prd",
        approvals_status={"prd": "approved", "server_details_client": "approved"},
    )
    result = prd_approval_gate(state)
    assert result["pause_reason"] is None


def test_prd_gate_unset_creates_pending_and_pauses():
    """Gate sets pending status if not already set."""
    state = _make_state(current_phase="prd")  # no approvals_status
    result = prd_approval_gate(state)
    assert result["pause_reason"] == "waiting_approval"
    from app.sot.state import ProjectState
    sot = ProjectState(**result["sot"])
    assert sot.approvals_status.get("prd") == ApprovalStatus.PENDING
    assert sot.approvals_status.get("server_details_client") == ApprovalStatus.PENDING


# ── sow_phase + sow_gate ──────────────────────────────────────────────────────

def test_sow_phase_sets_phase():
    settings.USE_MOCK_AGENTS = True
    state = _make_state(current_phase="prd")
    result = sow_phase(state)
    from app.sot.state import ProjectState
    sot = ProjectState(**result["sot"])
    assert sot.current_phase == Phase.SOW


def test_sow_gate_pending_pauses():
    state = _make_state(current_phase="sow", approvals_status={"sow": "pending"})
    result = sow_approval_gate(state)
    assert result["pause_reason"] == "waiting_approval"


def test_sow_gate_approved_continues():
    state = _make_state(current_phase="sow", approvals_status={"sow": "approved"})
    result = sow_approval_gate(state)
    assert result["pause_reason"] is None


# ── end_node ──────────────────────────────────────────────────────────────────

def test_end_node_sets_completed():
    state = _make_state(current_phase="sow")
    result = end_node(state)
    from app.sot.state import ProjectState
    sot = ProjectState(**result["sot"])
    assert sot.current_phase == Phase.COMPLETED


def test_end_node_no_pause():
    state = _make_state()
    result = end_node(state)
    assert result["pause_reason"] is None


# ── Full graph smoke test (no DB) ─────────────────────────────────────────────

def test_graph_compiles():
    """get_workflow() must not raise."""
    wf = get_workflow()
    assert wf is not None


def test_graph_invoke_pauses_at_discovery():
    """Full graph: start from INIT → should pause at discovery with waiting_user."""
    settings.USE_MOCK_AGENTS = True
    from app.sot.state import create_initial_state
    wf = get_workflow()
    # No user message yet → discovery pauses and asks the first question
    sot = create_initial_state(project_id=99, run_id=1, user_message=None)
    initial_state: WorkflowState = {
        "sot": sot.model_dump_jsonb(),
        "run_id": 1,
        "pause_reason": None,
        "bot_response": None,
        "approval_id": None,
    }
    result = wf.invoke(initial_state)
    assert result["pause_reason"] == "waiting_user"
    assert result["bot_response"] is not None


def test_graph_invoke_resumes_to_prd_gate():
    """Resume from discovery with an answer → pauses at prd_gate."""
    settings.USE_MOCK_AGENTS = True
    from app.sot.state import create_initial_state, ProjectState
    sot = create_initial_state(project_id=99, run_id=1)
    # Mock agent's "second call" heuristic requires at least one existing open question.
    sot = apply_patch(sot, {
        "current_phase": "discovery",
        "last_user_message": "Answer",
        "open_questions": [{"question": "What is the primary use case?", "category": "scope", "answered": False}],
    })

    wf = get_workflow()
    state: WorkflowState = {
        "sot": sot.model_dump_jsonb(),
        "run_id": 1,
        "pause_reason": None,
        "bot_response": None,
        "approval_id": None,
    }
    result = wf.invoke(state)
    assert result["pause_reason"] == "waiting_approval"
    final = ProjectState(**result["sot"])
    assert final.current_phase == Phase.PRD


def test_graph_invoke_approved_prd_continues_to_sow_gate():
    """PRD + server details approved → commercials runs → pauses at commercials gate."""
    settings.USE_MOCK_AGENTS = True
    from app.sot.state import create_initial_state, ProjectState
    sot = create_initial_state(project_id=99, run_id=1)
    sot = apply_patch(sot, {
        "current_phase": "prd",
        "approvals_status": {"prd": "approved", "server_details_client": "approved"},
    })
    wf = get_workflow()
    state: WorkflowState = {
        "sot": sot.model_dump_jsonb(),
        "run_id": 1,
        "pause_reason": None,
        "bot_response": None,
        "approval_id": None,
    }
    result = wf.invoke(state)
    assert result["pause_reason"] == "waiting_approval"
    final = ProjectState(**result["sot"])
    assert final.current_phase == Phase.COMMERCIALS


def test_graph_invoke_approved_sow_proceeds_to_coding_plan():
    """SOW approved → coding_plan runs → pauses at coding_plan_gate for tech lead sign-off."""
    settings.USE_MOCK_AGENTS = True
    from app.sot.state import create_initial_state, ProjectState
    sot = create_initial_state(project_id=99, run_id=1)
    sot = apply_patch(sot, {
        "current_phase": "sow",
        "approvals_status": {"sow": "approved"},
    })
    wf = get_workflow()
    state: WorkflowState = {
        "sot": sot.model_dump_jsonb(),
        "run_id": 1,
        "pause_reason": None,
        "bot_response": None,
        "approval_id": None,
    }
    result = wf.invoke(state)
    # After SOW approval the workflow now proceeds to coding_plan_gate, not end.
    assert result["pause_reason"] == "waiting_approval"
    final = ProjectState(**result["sot"])
    assert final.current_phase == Phase.CODING
    assert len(final.coding_plan) > 0
