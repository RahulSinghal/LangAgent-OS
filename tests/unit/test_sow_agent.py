"""Unit tests for app/agents/sow_agent.py — Phase 4.

All LLM calls are mocked. No API keys or DB access required.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.agents.sow_agent import SOWAgent
from app.registry.loader import AgentSpec, AgentLimits
from app.sot.state import ApprovalStatus, ProjectState


def _make_spec() -> AgentSpec:
    return AgentSpec(
        name="SOWAgent",
        role="engagement_manager",
        description="test",
        allowed_tools=[],
        limits=AgentLimits(max_steps=5, max_tool_calls=0, budget_usd=1.0),
    )


def _make_state(**kwargs) -> ProjectState:
    defaults = dict(project_id=1, run_id=1)
    defaults.update(kwargs)
    return ProjectState(**defaults)


def _sow_sections_response() -> list:
    return [
        {"title": "Executive Summary", "content": "This SOW covers the CRM build."},
        {"title": "Project Scope", "content": "In scope: SSO, contacts, reports."},
        {"title": "Deliverables", "content": "Web application, API documentation."},
        {"title": "Timeline & Milestones", "content": "6 months total."},
        {"title": "Commercials & Payment Terms", "content": "Fixed price £250k."},
        {"title": "Assumptions & Constraints", "content": "Client provides AD."},
        {"title": "Acceptance Criteria", "content": "UAT sign-off required."},
        {"title": "Risks & Mitigations", "content": "Vendor dependency risk."},
        {"title": "Governance & Communication", "content": "Weekly steering."},
    ]


class TestSOWAgentPhaseAndApproval:

    def test_sets_current_phase_to_sow(self):
        agent = SOWAgent(_make_spec())
        state = _make_state()

        with patch("app.services.llm_service.call_llm_json") as mock_json:
            mock_json.side_effect = [
                _sow_sections_response(),   # generate_sow_sections
                {"flags": []},              # legal_guard_check
            ]
            patch_result = agent.run(state)

        assert patch_result["current_phase"] == "sow"

    def test_sets_sow_approval_to_pending(self):
        agent = SOWAgent(_make_spec())
        state = _make_state()

        with patch("app.services.llm_service.call_llm_json") as mock_json:
            mock_json.side_effect = [_sow_sections_response(), {"flags": []}]
            patch_result = agent.run(state)

        assert patch_result["approvals_status"]["sow"] == ApprovalStatus.PENDING.value

    def test_sow_sections_in_patch(self):
        agent = SOWAgent(_make_spec())
        state = _make_state()

        with patch("app.services.llm_service.call_llm_json") as mock_json:
            mock_json.side_effect = [_sow_sections_response(), {"flags": []}]
            patch_result = agent.run(state)

        assert len(patch_result["sow_sections"]) == 9
        assert patch_result["sow_sections"][0]["title"] == "Executive Summary"

    def test_clears_rejection_feedback(self):
        agent = SOWAgent(_make_spec())
        state = _make_state(
            rejection_feedback={"artifact_type": "sow", "comment": "Add liability cap"}
        )

        with patch("app.services.llm_service.call_llm_json") as mock_json:
            mock_json.side_effect = [_sow_sections_response(), {"flags": []}]
            patch_result = agent.run(state)

        assert patch_result["rejection_feedback"] is None


class TestSOWAgentRejectionFeedback:

    def test_rejection_feedback_in_section_generation_prompt(self):
        agent = SOWAgent(_make_spec())
        state = _make_state(
            rejection_feedback={"artifact_type": "sow", "comment": "Add liability cap clause"}
        )

        with patch("app.services.llm_service.call_llm_json") as mock_json:
            mock_json.side_effect = [_sow_sections_response(), {"flags": []}]
            agent.run(state)

        # First call is generate_sow_sections
        first_call = mock_json.call_args_list[0]
        system_prompt = first_call.args[0] if first_call.args else ""
        assert "Add liability cap clause" in system_prompt

    def test_other_artifact_feedback_not_included(self):
        agent = SOWAgent(_make_spec())
        state = _make_state(
            rejection_feedback={"artifact_type": "prd", "comment": "PRD feedback"}
        )

        with patch("app.services.llm_service.call_llm_json") as mock_json:
            mock_json.side_effect = [_sow_sections_response(), {"flags": []}]
            agent.run(state)

        first_call = mock_json.call_args_list[0]
        system_prompt = first_call.args[0] if first_call.args else ""
        assert "PRD feedback" not in system_prompt


class TestSOWAgentLegalGuardCheck:

    def test_legal_guard_check_called(self):
        agent = SOWAgent(_make_spec())
        state = _make_state()

        with patch("app.services.llm_service.call_llm_json") as mock_json:
            mock_json.side_effect = [_sow_sections_response(), {"flags": ["Unlimited liability"]}]
            agent.run(state)

        # legal_guard_check is the second call
        assert mock_json.call_count == 2

    def test_empty_sections_skips_legal_guard_check(self):
        agent = SOWAgent(_make_spec())
        # Directly test _legal_guard_check with empty sections
        with patch("app.services.llm_service.call_llm_json") as mock_json:
            flags = agent._legal_guard_check([], mock_json)
        # Should return [] without calling LLM
        mock_json.assert_not_called()
        assert flags == []


class TestSOWAgentFallback:

    def test_fallback_empty_sections_on_generation_error(self):
        agent = SOWAgent(_make_spec())
        state = _make_state()

        with patch("app.services.llm_service.call_llm_json") as mock_json:
            # First call (generate) fails
            mock_json.side_effect = [Exception("API error"), {"flags": []}]
            patch_result = agent.run(state)

        assert patch_result["sow_sections"] == []
        assert patch_result["current_phase"] == "sow"

    def test_sections_dict_with_sections_key_handled(self):
        """Some models return {"sections": [...]} instead of a list."""
        agent = SOWAgent(_make_spec())
        state = _make_state()

        wrapped_response = {"sections": _sow_sections_response()}

        with patch("app.services.llm_service.call_llm_json") as mock_json:
            mock_json.side_effect = [wrapped_response, {"flags": []}]
            patch_result = agent.run(state)

        assert len(patch_result["sow_sections"]) == 9
