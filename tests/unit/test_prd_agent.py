"""Unit tests for app/agents/prd_agent.py — Phase 4.

All LLM calls are mocked. No API keys or DB access required.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.agents.prd_agent import PRDAgent
from app.registry.loader import AgentSpec, AgentLimits
from app.sot.state import ApprovalStatus, ProjectState, RequirementItem


def _make_spec() -> AgentSpec:
    return AgentSpec(
        name="PRDAgent",
        role="product_manager",
        description="test",
        allowed_tools=[],
        limits=AgentLimits(max_steps=5, max_tool_calls=0, budget_usd=1.0),
    )


def _make_state(**kwargs) -> ProjectState:
    defaults = dict(project_id=1, run_id=1)
    defaults.update(kwargs)
    return ProjectState(**defaults)


def _scope_response() -> dict:
    return {
        "summary": "A CRM system for enterprise sales teams",
        "in_scope": ["SSO", "Contact management"],
        "out_of_scope": ["Mobile app"],
        "key_deliverables": ["Web application"],
        "constraints": ["6 months timeline"],
        "success_criteria": ["1000 active users in month 1"],
    }


# ── Phase and approval tests ────────────────────────────────────────────────────

class TestPRDAgentPhaseAndApproval:

    def test_sets_current_phase_to_prd(self):
        agent = PRDAgent(_make_spec())
        state = _make_state()

        with patch("app.services.llm_service.call_llm_json", return_value=_scope_response()), \
             patch("app.services.llm_service.call_llm", return_value="PRD narrative"):
            patch_result = agent.run(state)

        assert patch_result["current_phase"] == "prd"

    def test_sets_prd_approval_to_pending(self):
        agent = PRDAgent(_make_spec())
        state = _make_state()

        with patch("app.services.llm_service.call_llm_json", return_value=_scope_response()), \
             patch("app.services.llm_service.call_llm", return_value="PRD narrative"):
            patch_result = agent.run(state)

        assert patch_result["approvals_status"]["prd"] == ApprovalStatus.PENDING.value

    def test_generates_scope_in_patch(self):
        agent = PRDAgent(_make_spec())
        state = _make_state()

        with patch("app.services.llm_service.call_llm_json", return_value=_scope_response()), \
             patch("app.services.llm_service.call_llm", return_value="PRD narrative"):
            patch_result = agent.run(state)

        assert patch_result["scope"]["summary"] == "A CRM system for enterprise sales teams"

    def test_clears_rejection_feedback(self):
        agent = PRDAgent(_make_spec())
        state = _make_state(
            rejection_feedback={"artifact_type": "prd", "comment": "Needs NFRs"}
        )

        with patch("app.services.llm_service.call_llm_json", return_value=_scope_response()), \
             patch("app.services.llm_service.call_llm", return_value="PRD narrative"):
            patch_result = agent.run(state)

        assert patch_result["rejection_feedback"] is None


# ── Rejection feedback context ──────────────────────────────────────────────────

class TestPRDAgentRejectionFeedback:

    def test_rejection_feedback_included_in_scope_prompt(self):
        agent = PRDAgent(_make_spec())
        state = _make_state(
            rejection_feedback={"artifact_type": "prd", "comment": "Add security section"}
        )

        with patch("app.services.llm_service.call_llm_json") as mock_json, \
             patch("app.services.llm_service.call_llm", return_value="narrative"):
            mock_json.return_value = _scope_response()
            agent.run(state)

        # The system prompt passed to call_llm_json should contain the feedback
        call_args = mock_json.call_args
        system_prompt = call_args.args[0] if call_args.args else call_args.kwargs.get("system_prompt", "")
        assert "Add security section" in system_prompt

    def test_no_feedback_context_when_rejection_feedback_is_none(self):
        agent = PRDAgent(_make_spec())
        state = _make_state()

        with patch("app.services.llm_service.call_llm_json") as mock_json, \
             patch("app.services.llm_service.call_llm", return_value="narrative"):
            mock_json.return_value = _scope_response()
            agent.run(state)

        call_args = mock_json.call_args
        system_prompt = call_args.args[0] if call_args.args else ""
        assert "REJECTION FEEDBACK" not in system_prompt

    def test_feedback_context_only_for_matching_artifact_type(self):
        agent = PRDAgent(_make_spec())
        # rejection is for SOW, not PRD — should not appear in PRD prompt
        state = _make_state(
            rejection_feedback={"artifact_type": "sow", "comment": "SOW needs fixing"}
        )

        with patch("app.services.llm_service.call_llm_json") as mock_json, \
             patch("app.services.llm_service.call_llm", return_value="narrative"):
            mock_json.return_value = _scope_response()
            agent.run(state)

        call_args = mock_json.call_args
        system_prompt = call_args.args[0] if call_args.args else ""
        assert "SOW needs fixing" not in system_prompt


# ── Fallback on LLM error ──────────────────────────────────────────────────────

class TestPRDAgentFallback:

    def test_fallback_scope_returned_on_llm_json_error(self):
        agent = PRDAgent(_make_spec())
        state = _make_state()

        with patch("app.services.llm_service.call_llm_json", side_effect=Exception("API error")), \
             patch("app.services.llm_service.call_llm", return_value="narrative"):
            patch_result = agent.run(state)

        # Fallback scope should still be returned
        assert "scope" in patch_result
        assert patch_result["scope"]["summary"] == "To be defined"
