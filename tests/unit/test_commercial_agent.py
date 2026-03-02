"""Unit tests for app/agents/commercial_agent.py — Phase 4.

All LLM calls are mocked. No API keys or DB access required.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.agents.commercial_agent import CommercialAgent
from app.registry.loader import AgentSpec, AgentLimits
from app.sot.state import ApprovalStatus, ProjectState


def _make_spec() -> AgentSpec:
    return AgentSpec(
        name="CommercialAgent",
        role="engagement_manager",
        description="test",
        allowed_tools=[],
        limits=AgentLimits(max_steps=5, max_tool_calls=0, budget_usd=1.0),
    )


def _make_state(**kwargs) -> ProjectState:
    defaults = dict(project_id=1, run_id=1)
    defaults.update(kwargs)
    return ProjectState(**defaults)


def _commercials_response() -> dict:
    return {
        "commercial_model": "Fixed price — 6 month engagement",
        "milestones": [
            {"name": "Phase 1 — Discovery", "duration": "4 weeks",
             "deliverables": ["BRD"], "payment_pct": 20},
            {"name": "Phase 2 — Build", "duration": "16 weeks",
             "deliverables": ["Working software"], "payment_pct": 60},
            {"name": "Phase 3 — UAT & Go-Live", "duration": "4 weeks",
             "deliverables": ["Deployed app"], "payment_pct": 20},
        ],
        "team_composition": [{"role": "Tech Lead", "count": 1, "rate_range": "£700-£900/day"}],
        "total_estimate": "£250,000",
        "payment_terms": "30 days net",
        "assumptions": ["Client provides environment access"],
    }


class TestCommercialAgentPhaseAndApproval:

    def test_sets_current_phase_to_commercials(self):
        agent = CommercialAgent(_make_spec())
        state = _make_state()

        with patch("app.services.llm_service.call_llm_json", return_value=_commercials_response()):
            patch_result = agent.run(state)

        assert patch_result["current_phase"] == "commercials"

    def test_sets_commercials_approval_to_pending(self):
        agent = CommercialAgent(_make_spec())
        state = _make_state()

        with patch("app.services.llm_service.call_llm_json", return_value=_commercials_response()):
            patch_result = agent.run(state)

        assert patch_result["approvals_status"]["commercials"] == ApprovalStatus.PENDING.value

    def test_commercial_model_in_patch(self):
        agent = CommercialAgent(_make_spec())
        state = _make_state()

        with patch("app.services.llm_service.call_llm_json", return_value=_commercials_response()):
            patch_result = agent.run(state)

        assert "Fixed price" in patch_result["commercial_model"]

    def test_milestones_in_patch(self):
        agent = CommercialAgent(_make_spec())
        state = _make_state()

        with patch("app.services.llm_service.call_llm_json", return_value=_commercials_response()):
            patch_result = agent.run(state)

        assert len(patch_result["milestones"]) == 3

    def test_clears_rejection_feedback(self):
        agent = CommercialAgent(_make_spec())
        state = _make_state(
            rejection_feedback={"artifact_type": "commercials", "comment": "Reduce margin"}
        )

        with patch("app.services.llm_service.call_llm_json", return_value=_commercials_response()):
            patch_result = agent.run(state)

        assert patch_result["rejection_feedback"] is None


class TestCommercialAgentRejectionFeedback:

    def test_rejection_feedback_included_in_prompt(self):
        agent = CommercialAgent(_make_spec())
        state = _make_state(
            rejection_feedback={"artifact_type": "commercials", "comment": "Lower the rate"}
        )

        with patch("app.services.llm_service.call_llm_json") as mock_json:
            mock_json.return_value = _commercials_response()
            agent.run(state)

        call_args = mock_json.call_args
        system_prompt = call_args.args[0] if call_args.args else ""
        assert "Lower the rate" in system_prompt

    def test_other_artifact_feedback_not_included(self):
        agent = CommercialAgent(_make_spec())
        state = _make_state(
            rejection_feedback={"artifact_type": "prd", "comment": "PRD needs fixing"}
        )

        with patch("app.services.llm_service.call_llm_json") as mock_json:
            mock_json.return_value = _commercials_response()
            agent.run(state)

        call_args = mock_json.call_args
        system_prompt = call_args.args[0] if call_args.args else ""
        assert "PRD needs fixing" not in system_prompt


class TestCommercialAgentFallback:

    def test_fallback_commercials_returned_on_llm_error(self):
        agent = CommercialAgent(_make_spec())
        state = _make_state()

        with patch("app.services.llm_service.call_llm_json", side_effect=Exception("API down")):
            patch_result = agent.run(state)

        assert patch_result["commercial_model"] == "To be determined"
        assert patch_result["milestones"] == []
        assert patch_result["current_phase"] == "commercials"
