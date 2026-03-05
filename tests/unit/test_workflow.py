"""Unit tests for Phase 1E — workflow nodes and graph routing (no DB required)."""

import pytest

from app.core.config import settings
from app.sot.patch import apply_patch
from app.sot.state import ApprovalStatus, Phase, create_initial_state
from app.workflow.graph import WorkflowState, _route_entry, _route_after_discovery, get_workflow
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


# ── _route_after_discovery ────────────────────────────────────────────────────

def test_route_after_discovery_pause_takes_priority():
    """pause_reason always returns 'pause' regardless of document_type."""
    state = _make_state(current_phase="discovery", document_type="technical_design")
    state["pause_reason"] = "waiting_user"
    assert _route_after_discovery(state) == "pause"


def test_route_after_discovery_technical_design_returns_fast_coding():
    """technical_design doc → fast_coding to coding_plan generator."""
    state = _make_state(current_phase="discovery", document_type="technical_design")
    state["pause_reason"] = None
    assert _route_after_discovery(state) == "fast_coding"


def test_route_after_discovery_prd_returns_fast_prd():
    """PRD doc → fast_prd; uploaded doc IS the PRD, skip generation."""
    state = _make_state(current_phase="discovery", document_type="prd")
    state["pause_reason"] = None
    assert _route_after_discovery(state) == "fast_prd"


def test_route_after_discovery_sow_returns_fast_sow():
    """SOW doc → fast_sow; uploaded doc IS the SOW, skip generation."""
    state = _make_state(current_phase="discovery", document_type="sow")
    state["pause_reason"] = None
    assert _route_after_discovery(state) == "fast_sow"


def test_route_after_discovery_market_eval_returns_fast_market_eval():
    """market_eval doc → fast_market_eval; skip market_eval generation."""
    state = _make_state(current_phase="discovery", document_type="market_eval")
    state["pause_reason"] = None
    assert _route_after_discovery(state) == "fast_market_eval"


def test_route_after_discovery_commercials_returns_fast_commercials():
    """commercials doc → fast_commercials; skip commercials generation."""
    state = _make_state(current_phase="discovery", document_type="commercials")
    state["pause_reason"] = None
    assert _route_after_discovery(state) == "fast_commercials"


def test_route_after_discovery_no_document_type_returns_continue():
    """No document_type set → normal continue to market_eval."""
    state = _make_state(current_phase="discovery")
    state["pause_reason"] = None
    assert _route_after_discovery(state) == "continue"


def test_route_after_discovery_brd_returns_continue():
    """BRD goes through the normal market_eval path (gap Q&A handled in discovery)."""
    state = _make_state(current_phase="discovery", document_type="brd")
    state["pause_reason"] = None
    assert _route_after_discovery(state) == "continue"


def test_route_after_discovery_unknown_returns_continue():
    """Unknown doc type → normal continue, no fast-track."""
    state = _make_state(current_phase="discovery", document_type="unknown")
    state["pause_reason"] = None
    assert _route_after_discovery(state) == "continue"


# ── discovery_loop: current_phase set on fast-track completion ────────────────

def test_discovery_loop_sets_phase_for_prd_doc_on_completion():
    """When discovery completes with document_type='prd', current_phase is set to 'prd'
    so that _route_after_discovery → fast_prd → prd_gate sees the right phase."""
    settings.USE_MOCK_AGENTS = True
    from app.sot.state import ProjectState
    state = _make_state(
        current_phase="discovery",
        last_user_message="Here is our PRD.",
        document_type="prd",
        open_questions=[
            {"question": "Any timeline constraints?", "category": "timeline", "answered": False}
        ],
    )
    result = discovery_loop(state)
    # Mock agent completes on second call (prior question + last_user_message)
    if result["pause_reason"] is None:
        sot = ProjectState(**result["sot"])
        assert sot.current_phase.value == "prd"


def test_discovery_loop_sets_phase_for_sow_doc_on_completion():
    """When discovery completes with document_type='sow', current_phase is set to 'sow'."""
    settings.USE_MOCK_AGENTS = True
    from app.sot.state import ProjectState
    state = _make_state(
        current_phase="discovery",
        last_user_message="Our SOW is attached.",
        document_type="sow",
        open_questions=[
            {"question": "Confirm payment terms?", "category": "commercials", "answered": False}
        ],
    )
    result = discovery_loop(state)
    if result["pause_reason"] is None:
        sot = ProjectState(**result["sot"])
        assert sot.current_phase.value == "sow"


def test_discovery_loop_no_phase_change_for_technical_design():
    """technical_design is handled by the coding_plan node — discovery should NOT
    pre-set current_phase for it."""
    settings.USE_MOCK_AGENTS = True
    from app.sot.state import ProjectState
    state = _make_state(
        current_phase="discovery",
        last_user_message="Architecture doc attached.",
        document_type="technical_design",
        open_questions=[
            {"question": "Tech stack?", "category": "architecture", "answered": False}
        ],
    )
    result = discovery_loop(state)
    if result["pause_reason"] is None:
        sot = ProjectState(**result["sot"])
        # Should still be "discovery" — coding_plan node sets CODING later
        assert sot.current_phase.value == "discovery"


# ── full graph: technical_design fast-track ───────────────────────────────────

def test_graph_invoke_technical_design_fast_tracks_to_coding_plan():
    """Discovery with a technical_design doc completes → skips market_eval/PRD/SOW,
    proceeds directly to coding_plan, pauses at coding_plan_gate."""
    settings.USE_MOCK_AGENTS = True
    from app.sot.state import create_initial_state, ProjectState
    sot = create_initial_state(project_id=99, run_id=1)
    # Mimic a resumed run: user answered a gap question, prior question in state
    # for the mock agent's second-call heuristic, document_type is set.
    sot = apply_patch(sot, {
        "current_phase": "discovery",
        "last_user_message": "The system uses microservices architecture.",
        "document_type": "technical_design",
        "open_questions": [
            {"question": "What is the overall architecture?", "category": "architecture", "answered": False}
        ],
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
    # Should pause at coding_plan_gate, NOT at market_eval_gate or prd_gate
    assert result["pause_reason"] == "waiting_approval"
    final = ProjectState(**result["sot"])
    assert final.current_phase == Phase.CODING
    assert len(final.coding_plan) > 0  # coding_plan was generated


def test_graph_invoke_approved_sow_proceeds_to_user_guide_gate():
    """SOW approved → user_guide node asks if guide is wanted → pauses waiting_user."""
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
    # After SOW approval the workflow now pauses at the user_guide node
    # to ask the user if they want a guide (waiting_user, not waiting_approval).
    assert result["pause_reason"] == "waiting_user"
    final = ProjectState(**result["sot"])
    assert final.current_phase == Phase.USER_GUIDE


def test_graph_invoke_user_guide_skipped_proceeds_to_coding_plan():
    """user_guide=no → workflow proceeds to coding_plan → pauses at coding_plan_gate."""
    settings.USE_MOCK_AGENTS = True
    from app.sot.state import create_initial_state, ProjectState
    sot = create_initial_state(project_id=99, run_id=1)
    sot = apply_patch(sot, {
        "current_phase": "user_guide",
        "approvals_status": {"sow": "approved"},
        "last_user_message": "no",
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
    # Skipped guide → coding_plan runs → pauses at coding_plan_gate
    assert result["pause_reason"] == "waiting_approval"
    final = ProjectState(**result["sot"])
    assert final.current_phase == Phase.CODING
    assert len(final.coding_plan) > 0
