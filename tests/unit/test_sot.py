"""Unit tests for Phase 1C — SoT state model and patch engine."""

import pytest

from app.sot.state import (
    ApprovalStatus,
    ArtifactRef,
    AssumptionItem,
    DecisionItem,
    Phase,
    Priority,
    ProjectState,
    QuestionItem,
    RequirementItem,
    RiskItem,
    create_initial_state,
)
from app.sot.patch import apply_patch


# ── create_initial_state ──────────────────────────────────────────────────────

def test_create_initial_state_defaults():
    state = create_initial_state(project_id=1)
    assert state.project_id == 1
    assert state.run_id is None
    assert state.session_id is None
    assert state.current_phase == Phase.INIT
    assert state.last_user_message is None
    assert state.requirements == []
    assert state.assumptions == []
    assert state.decisions == []
    assert state.risks == []
    assert state.open_questions == []
    assert state.artifacts_index == {}
    assert state.approvals_status == {}


def test_create_initial_state_with_args():
    state = create_initial_state(
        project_id=42,
        run_id=7,
        session_id=3,
        user_message="Hello system",
    )
    assert state.project_id == 42
    assert state.run_id == 7
    assert state.session_id == 3
    assert state.last_user_message == "Hello system"


# ── model_dump_jsonb ──────────────────────────────────────────────────────────

def test_model_dump_jsonb_is_json_serialisable():
    import json
    state = create_initial_state(project_id=1, run_id=1)
    blob = state.model_dump_jsonb()
    # Must not raise
    serialized = json.dumps(blob)
    assert '"project_id"' in serialized


def test_model_dump_jsonb_roundtrip():
    """Serialized state can be reconstructed into an identical ProjectState."""
    original = create_initial_state(project_id=5, run_id=10, user_message="start")
    blob = original.model_dump_jsonb()
    restored = ProjectState(**blob)
    assert restored.project_id == original.project_id
    assert restored.run_id == original.run_id
    assert restored.last_user_message == original.last_user_message
    assert restored.current_phase == original.current_phase


# ── ProjectState sub-models ───────────────────────────────────────────────────

def test_requirement_item_defaults():
    req = RequirementItem(category="functional", text="User can log in")
    assert req.priority == Priority.MEDIUM
    assert req.source == "discovery"
    assert req.accepted is True
    assert len(req.id) == 8


def test_question_item():
    q = QuestionItem(question="What is the primary use case?", category="scope")
    assert q.answered is False
    assert q.answer is None


def test_risk_item_defaults():
    r = RiskItem(description="Vendor lock-in")
    assert r.likelihood == "medium"
    assert r.impact == "medium"
    assert r.mitigation == ""


def test_artifact_ref():
    ref = ArtifactRef(version=2, artifact_id=99)
    assert ref.version == 2
    assert ref.artifact_id == 99


def test_state_with_full_content():
    state = ProjectState(
        project_id=1,
        current_phase=Phase.PRD,
        requirements=[RequirementItem(category="functional", text="Login")],
        risks=[RiskItem(description="Scope creep")],
        approvals_status={"prd": ApprovalStatus.PENDING},
        artifacts_index={"prd": ArtifactRef(version=1, artifact_id=5)},
    )
    assert state.current_phase == Phase.PRD
    assert len(state.requirements) == 1
    assert state.approvals_status["prd"] == ApprovalStatus.PENDING
    assert state.artifacts_index["prd"].artifact_id == 5


# ── apply_patch ───────────────────────────────────────────────────────────────

def test_apply_patch_phase_transition():
    state = create_initial_state(project_id=1)
    updated = apply_patch(state, {"current_phase": "discovery"})
    assert updated.current_phase == Phase.DISCOVERY
    assert updated.project_id == 1  # unchanged field preserved


def test_apply_patch_user_message():
    state = create_initial_state(project_id=1)
    updated = apply_patch(state, {"last_user_message": "Tell me more"})
    assert updated.last_user_message == "Tell me more"


def test_apply_patch_replaces_list():
    state = create_initial_state(project_id=1)
    req = {"category": "functional", "text": "Feature A"}
    updated = apply_patch(state, {"requirements": [req]})
    assert len(updated.requirements) == 1
    assert updated.requirements[0].text == "Feature A"


def test_apply_patch_multiple_fields():
    state = create_initial_state(project_id=1)
    patch = {
        "current_phase": "prd",
        "last_user_message": "ready",
        "approvals_status": {"prd": "pending"},
    }
    updated = apply_patch(state, patch)
    assert updated.current_phase == Phase.PRD
    assert updated.last_user_message == "ready"
    assert updated.approvals_status["prd"] == ApprovalStatus.PENDING


def test_apply_patch_unknown_field_raises():
    state = create_initial_state(project_id=1)
    with pytest.raises(ValueError, match="unknown"):
        apply_patch(state, {"nonexistent_field": "boom"})


def test_apply_patch_invalid_phase_raises():
    state = create_initial_state(project_id=1)
    with pytest.raises(ValueError):
        apply_patch(state, {"current_phase": "totally_invalid_phase"})


def test_apply_patch_empty_patch_returns_same():
    state = create_initial_state(project_id=1)
    updated = apply_patch(state, {})
    assert updated.project_id == state.project_id
    assert updated.current_phase == state.current_phase


def test_apply_patch_does_not_mutate_original():
    state = create_initial_state(project_id=1)
    apply_patch(state, {"current_phase": "prd"})
    # Original must be unchanged
    assert state.current_phase == Phase.INIT


def test_apply_patch_preserves_existing_lists():
    """Fields not in the patch must be preserved from original state."""
    state = create_initial_state(project_id=1)
    state_with_reqs = apply_patch(
        state,
        {"requirements": [{"category": "functional", "text": "Req 1"}]},
    )
    # Now patch only the phase — requirements must survive
    final = apply_patch(state_with_reqs, {"current_phase": "prd"})
    assert len(final.requirements) == 1
    assert final.requirements[0].text == "Req 1"
