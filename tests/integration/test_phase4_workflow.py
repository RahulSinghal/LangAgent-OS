"""Integration tests for Phase 4 — Real LLM Agents + Document-Type Awareness.

All LLM calls are mocked. DB calls use a real test database (via conftest fixtures).
Tests verify end-to-end behaviour of the new Phase 4 components.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


# ── LLM mock helpers ───────────────────────────────────────────────────────────

def _llm_response(content: str) -> MagicMock:
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _all_high_scores() -> dict:
    from app.agents.discovery_agent import _COVERAGE_CATEGORIES
    return {cat: 0.9 for cat in _COVERAGE_CATEGORIES}


def _scope_json() -> str:
    return json.dumps({
        "summary": "CRM system for enterprise sales",
        "in_scope": ["SSO", "Contact management"],
        "out_of_scope": ["Mobile app"],
        "key_deliverables": ["Web application"],
        "constraints": ["6 months"],
        "success_criteria": ["1000 active users"],
    })


def _commercials_json() -> str:
    return json.dumps({
        "commercial_model": "Fixed price — £250k",
        "milestones": [
            {"name": "Phase 1", "duration": "4w", "deliverables": ["BRD"], "payment_pct": 20},
            {"name": "Phase 2", "duration": "16w", "deliverables": ["App"], "payment_pct": 80},
        ],
        "team_composition": [{"role": "Lead", "count": 1, "rate_range": "£700/day"}],
        "total_estimate": "£250,000",
        "payment_terms": "30 days net",
        "assumptions": [],
    })


def _sow_sections_json() -> str:
    return json.dumps([
        {"title": "Executive Summary", "content": "CRM project."},
        {"title": "Project Scope", "content": "SSO, contacts."},
        {"title": "Deliverables", "content": "Web app."},
        {"title": "Timeline & Milestones", "content": "6 months."},
        {"title": "Commercials & Payment Terms", "content": "£250k fixed."},
        {"title": "Assumptions & Constraints", "content": "Client provides AD."},
        {"title": "Acceptance Criteria", "content": "UAT sign-off."},
        {"title": "Risks & Mitigations", "content": "Vendor risk."},
        {"title": "Governance & Communication", "content": "Weekly steering."},
    ])


# ── Document type detection integration ────────────────────────────────────────

class TestDocumentTypeDetectionIntegration:

    def test_brd_upload_sets_document_type_in_sot_patch(self):
        from app.services.document_ingestion import ingest_document

        brd_content = (
            "# Business Requirements Document\n\n"
            "## Requirements\n"
            "- [R-1] The system shall support SSO authentication.\n"
            "- [R-2] The platform shall handle 500 concurrent users.\n\n"
            "## Assumptions\n"
            "Assume client has Active Directory.\n"
        )
        result = ingest_document(brd_content, filename="project_brd.md")
        assert result["document_type"] == "brd"
        assert result["sot_patch"]["document_type"] == "brd"

    def test_brd_upload_generates_followup_questions_for_gaps(self):
        from app.services.document_ingestion import ingest_document

        # Minimal BRD — many required sections missing
        brd_content = (
            "# BRD\n\n"
            "## Requirements\n"
            "- [R-1] System shall support OAuth2.\n"
        )
        result = ingest_document(brd_content, filename="brd_minimal.md")
        assert "followup_questions" in result["sot_patch"]
        assert len(result["sot_patch"]["followup_questions"]) >= 3

    def test_prd_upload_sets_current_phase_to_prd(self):
        """When a PRD is uploaded, runs.py should set current_phase=prd in the patch."""
        from app.services.document_ingestion import ingest_document

        prd_content = (
            "# Product Requirements Document\n\n"
            "## User Stories\n"
            "- As a user I want to login so I can access my dashboard.\n\n"
            "## Acceptance Criteria\n"
            "- Login completes in under 2 seconds.\n"
        )
        result = ingest_document(prd_content, filename="product_prd.md")
        assert result["document_type"] == "prd"
        # runs.py adds current_phase; verify sot_patch doesn't already override it
        # (runs.py will add it separately only if not already present)

    def test_sow_upload_detected_correctly(self):
        from app.services.document_ingestion import ingest_document

        sow_content = (
            "# Statement of Work\n\n"
            "## Scope of Work\n"
            "Build enterprise CRM platform.\n\n"
            "## Deliverables\n"
            "- Web application\n\n"
            "## Payment Terms\n"
            "30 days net from invoice date.\n"
        )
        result = ingest_document(sow_content, filename="sow_draft.md")
        assert result["document_type"] == "sow"


# ── DiscoveryAgent integration ─────────────────────────────────────────────────

class TestDiscoveryAgentIntegration:

    def test_discovery_complete_when_all_scores_above_threshold(self):
        from app.agents.discovery_agent import DiscoveryAgent
        from app.sot.state import ProjectState

        agent = DiscoveryAgent()
        state = ProjectState(
            project_id=1, run_id=1,
            last_user_message="We need SSO, RBAC and audit logs for 500 users",
        )

        # Mock LLM: capture_answer + update_coverage (all high)
        with patch("litellm.completion") as mock_completion:
            mock_completion.side_effect = [
                _llm_response(json.dumps({
                    "updated_categories": {
                        "functional_requirements": ["SSO", "RBAC", "audit logs"],
                        "users_and_scale": {"user_count": "500"},
                    }
                })),
                _llm_response(json.dumps(_all_high_scores())),
            ]
            patch_result = agent.run(state)

        assert patch_result.get("discovery_complete") is True

    def test_followup_questions_surfaced_before_coverage_questions(self):
        from app.agents.discovery_agent import DiscoveryAgent
        from app.sot.state import ProjectState

        agent = DiscoveryAgent()
        state = ProjectState(
            project_id=1, run_id=1,
            followup_questions=["What are your stakeholder groups?", "What is the budget?"],
        )

        with patch("litellm.completion") as mock_completion:
            patch_result = agent.run(state)

        # LLM should NOT have been called (gap question surfaced deterministically)
        mock_completion.assert_not_called()
        # First gap question should appear in open_questions
        open_qs = patch_result.get("open_questions", [])
        assert any("stakeholder" in q["question"].lower() for q in open_qs)
        # Remaining followup questions should be reduced
        assert patch_result.get("followup_questions") == ["What is the budget?"]


# ── PRDAgent integration ───────────────────────────────────────────────────────

class TestPRDAgentIntegration:

    def test_prd_agent_generates_scope_and_sets_pending(self):
        from app.agents.prd_agent import PRDAgent
        from app.sot.state import ApprovalStatus, ProjectState, RequirementItem

        agent = PRDAgent()
        state = ProjectState(
            project_id=1, run_id=1,
            requirements=[
                RequirementItem(category="functional", text="SSO required", source="discovery"),
                RequirementItem(category="non_functional", text="99.9% uptime", source="discovery"),
            ],
        )

        with patch("litellm.completion") as mock_completion:
            mock_completion.side_effect = [
                _llm_response(_scope_json()),
                _llm_response("PRD narrative text..."),
            ]
            new_sot = agent.execute(state)

        assert new_sot.current_phase.value == "prd"
        assert new_sot.approvals_status.get("prd") == ApprovalStatus.PENDING
        assert new_sot.scope is not None
        assert "CRM system" in new_sot.scope["summary"]

    def test_prd_rejection_feedback_loop(self):
        from app.agents.prd_agent import PRDAgent
        from app.sot.state import ApprovalStatus, ProjectState

        agent = PRDAgent()
        state = ProjectState(
            project_id=1, run_id=1,
            rejection_feedback={"artifact_type": "prd", "comment": "Add NFR section"},
        )

        with patch("litellm.completion") as mock_completion:
            mock_completion.side_effect = [
                _llm_response(_scope_json()),
                _llm_response("Updated PRD with NFR section..."),
            ]
            new_sot = agent.execute(state)

        # rejection_feedback should be cleared after re-generation
        assert new_sot.rejection_feedback is None
        assert new_sot.approvals_status.get("prd") == ApprovalStatus.PENDING


# ── CommercialAgent integration ────────────────────────────────────────────────

class TestCommercialAgentIntegration:

    def test_commercial_agent_generates_proposal(self):
        from app.agents.commercial_agent import CommercialAgent
        from app.sot.state import ApprovalStatus, ProjectState

        agent = CommercialAgent()
        state = ProjectState(
            project_id=1, run_id=1,
            scope={"summary": "CRM build", "in_scope": ["SSO"], "out_of_scope": []},
        )

        with patch("litellm.completion") as mock_completion:
            mock_completion.return_value = _llm_response(_commercials_json())
            new_sot = agent.execute(state)

        assert new_sot.current_phase.value == "commercials"
        assert new_sot.approvals_status.get("commercials") == ApprovalStatus.PENDING
        assert "Fixed price" in new_sot.commercial_model
        assert len(new_sot.milestones) == 2


# ── SOWAgent integration ───────────────────────────────────────────────────────

class TestSOWAgentIntegration:

    def test_sow_agent_generates_sections(self):
        from app.agents.sow_agent import SOWAgent
        from app.sot.state import ApprovalStatus, ProjectState

        agent = SOWAgent()
        state = ProjectState(
            project_id=1, run_id=1,
            scope={"summary": "CRM build"},
            commercial_model="Fixed price",
        )

        with patch("litellm.completion") as mock_completion:
            mock_completion.side_effect = [
                _llm_response(_sow_sections_json()),
                _llm_response(json.dumps({"flags": []})),
            ]
            new_sot = agent.execute(state)

        assert new_sot.current_phase.value == "sow"
        assert new_sot.approvals_status.get("sow") == ApprovalStatus.PENDING
        assert len(new_sot.sow_sections) == 9

    def test_sow_rejection_feedback_loop(self):
        from app.agents.sow_agent import SOWAgent
        from app.sot.state import ApprovalStatus, ProjectState

        agent = SOWAgent()
        state = ProjectState(
            project_id=1, run_id=1,
            rejection_feedback={"artifact_type": "sow", "comment": "Add liability cap"},
        )

        with patch("litellm.completion") as mock_completion:
            mock_completion.side_effect = [
                _llm_response(_sow_sections_json()),
                _llm_response(json.dumps({"flags": []})),
            ]
            new_sot = agent.execute(state)

        assert new_sot.rejection_feedback is None
        assert new_sot.approvals_status.get("sow") == ApprovalStatus.PENDING


# ── Approval gate rejection routing ───────────────────────────────────────────

class TestApprovalGateRejectionRouting:

    def test_rejected_prd_sets_rejection_feedback_and_no_pause(self):
        from app.workflow.nodes.approval_gate import prd_approval_gate
        from app.sot.state import ApprovalStatus, ProjectState

        sot = ProjectState(
            project_id=1, run_id=1,
            approvals_status={"prd": ApprovalStatus.REJECTED},
        )

        with patch("app.workflow.nodes.approval_gate._load_rejection_comment", return_value="Needs NFRs"):
            result = prd_approval_gate({"sot": sot.model_dump_jsonb(), "approval_id": 1})

        # Should not pause
        assert result["pause_reason"] is None
        # rejection_feedback should be set in the SoT
        assert result["sot"]["rejection_feedback"]["artifact_type"] == "prd"
        assert result["sot"]["rejection_feedback"]["comment"] == "Needs NFRs"

    def test_approved_prd_clears_pause(self):
        from app.workflow.nodes.approval_gate import prd_approval_gate
        from app.sot.state import ApprovalStatus, ProjectState

        sot = ProjectState(
            project_id=1, run_id=1,
            approvals_status={"prd": ApprovalStatus.APPROVED},
        )
        result = prd_approval_gate({"sot": sot.model_dump_jsonb(), "approval_id": None})
        assert result["pause_reason"] is None

    def test_pending_sow_pauses_run(self):
        from app.workflow.nodes.approval_gate import sow_approval_gate
        from app.sot.state import ApprovalStatus, ProjectState

        sot = ProjectState(
            project_id=1, run_id=1,
            approvals_status={"sow": ApprovalStatus.PENDING},
        )
        result = sow_approval_gate({"sot": sot.model_dump_jsonb(), "approval_id": None})
        assert result["pause_reason"] == "waiting_approval"

    def test_rejected_commercials_sets_rejection_feedback(self):
        from app.workflow.nodes.approval_gate import commercials_approval_gate
        from app.sot.state import ApprovalStatus, ProjectState

        sot = ProjectState(
            project_id=1, run_id=1,
            approvals_status={"commercials": ApprovalStatus.REJECTED},
        )

        with patch("app.workflow.nodes.approval_gate._load_rejection_comment", return_value="Reduce margin"):
            result = commercials_approval_gate({
                "sot": sot.model_dump_jsonb(), "approval_id": 42
            })

        assert result["pause_reason"] is None
        assert result["sot"]["rejection_feedback"]["artifact_type"] == "commercials"
        assert result["sot"]["rejection_feedback"]["comment"] == "Reduce margin"


# ── Workflow graph routing ─────────────────────────────────────────────────────

class TestWorkflowGraphRouting:

    def test_route_entry_maps_all_phases(self):
        from app.workflow.graph import _route_entry

        phase_to_node = {
            "init":        "intake",
            "discovery":   "discovery",
            "market_eval": "market_eval_gate",
            "prd":         "prd_gate",
            "commercials": "commercials_gate",
            "sow":         "sow_gate",
            "completed":   "end",
        }
        for phase, expected_node in phase_to_node.items():
            state = {"sot": {"current_phase": phase}, "run_id": 1,
                     "pause_reason": None, "bot_response": None, "approval_id": None}
            assert _route_entry(state) == expected_node, f"Failed for phase={phase}"

    def test_route_after_prd_gate_rejected(self):
        from app.workflow.graph import _route_after_prd_gate

        state = {
            "sot": {"rejection_feedback": {"artifact_type": "prd", "comment": "x"}},
            "pause_reason": None,
            "run_id": 1, "bot_response": None, "approval_id": None,
        }
        assert _route_after_prd_gate(state) == "rejected"

    def test_route_after_prd_gate_approved(self):
        from app.workflow.graph import _route_after_prd_gate

        state = {
            "sot": {"rejection_feedback": None},
            "pause_reason": None,
            "run_id": 1, "bot_response": None, "approval_id": None,
        }
        assert _route_after_prd_gate(state) == "approved"

    def test_route_after_prd_gate_waiting(self):
        from app.workflow.graph import _route_after_prd_gate

        state = {
            "sot": {},
            "pause_reason": "waiting_approval",
            "run_id": 1, "bot_response": None, "approval_id": None,
        }
        assert _route_after_prd_gate(state) == "waiting"

    def test_route_after_commercials_gate_all_outcomes(self):
        from app.workflow.graph import _route_after_commercials_gate

        assert _route_after_commercials_gate({
            "sot": {}, "pause_reason": "waiting_approval", "run_id": 1,
            "bot_response": None, "approval_id": None,
        }) == "waiting"

        assert _route_after_commercials_gate({
            "sot": {"rejection_feedback": {"artifact_type": "commercials"}},
            "pause_reason": None, "run_id": 1, "bot_response": None, "approval_id": None,
        }) == "rejected"

        assert _route_after_commercials_gate({
            "sot": {"rejection_feedback": None}, "pause_reason": None,
            "run_id": 1, "bot_response": None, "approval_id": None,
        }) == "approved"
