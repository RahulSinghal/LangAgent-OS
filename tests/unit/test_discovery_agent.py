"""Unit tests for app/agents/discovery_agent.py — Phase 4.

All LLM calls are mocked. No real API calls or DB access.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.agents.discovery_agent import DiscoveryAgent, _COVERAGE_THRESHOLD
from app.registry.loader import AgentSpec, AgentLimits
from app.sot.state import ProjectState, RequirementItem, QuestionItem


# ── Fixtures ───────────────────────────────────────────────────────────────────

def _make_spec() -> AgentSpec:
    return AgentSpec(
        name="DiscoveryAgent",
        role="analyst",
        description="test",
        allowed_tools=[],
        limits=AgentLimits(max_steps=50, max_tool_calls=0, budget_usd=2.0),
    )


def _make_state(**kwargs) -> ProjectState:
    defaults = dict(project_id=1, run_id=1)
    defaults.update(kwargs)
    return ProjectState(**defaults)


def _all_low_scores() -> dict:
    from app.agents.discovery_agent import _COVERAGE_CATEGORIES
    return {cat: 0.0 for cat in _COVERAGE_CATEGORIES}


def _all_high_scores() -> dict:
    from app.agents.discovery_agent import _COVERAGE_CATEGORIES
    return {cat: 0.8 for cat in _COVERAGE_CATEGORIES}


# ── Gate logic ─────────────────────────────────────────────────────────────────

class TestGatePassed:

    def test_returns_false_when_scores_empty(self):
        agent = DiscoveryAgent(_make_spec())
        assert agent._gate_passed({}) is False

    def test_returns_false_when_any_score_below_threshold(self):
        agent = DiscoveryAgent(_make_spec())
        scores = _all_high_scores()
        scores["business_context"] = 0.5  # below threshold
        assert agent._gate_passed(scores) is False

    def test_returns_true_when_all_scores_at_threshold(self):
        agent = DiscoveryAgent(_make_spec())
        scores = {cat: _COVERAGE_THRESHOLD for cat in scores_from_high()}
        # Use shortcut
        assert agent._gate_passed(_all_high_scores()) is True

    def test_returns_true_when_all_scores_above_threshold(self):
        agent = DiscoveryAgent(_make_spec())
        assert agent._gate_passed(_all_high_scores()) is True


def scores_from_high():
    from app.agents.discovery_agent import _COVERAGE_CATEGORIES
    return {cat: 0.8 for cat in _COVERAGE_CATEGORIES}


# ── Followup questions consumed first ─────────────────────────────────────────

class TestFollowupQuestionsPriority:

    def test_followup_questions_consumed_before_coverage_questions(self):
        """When followup_questions is non-empty, surface first one and reduce list."""
        agent = DiscoveryAgent(_make_spec())
        state = _make_state(
            followup_questions=["Question A?", "Question B?"],
            coverage_scores=_all_low_scores(),
        )

        with patch("app.services.llm_service.call_llm") as mock_llm, \
             patch("app.services.llm_service.call_llm_json") as mock_llm_json:
            patch_result = agent.run(state)

        # Should surface the first gap question
        open_qs = patch_result.get("open_questions", [])
        question_texts = [q["question"] for q in open_qs]
        assert "Question A?" in question_texts

        # followup_questions should be reduced by 1
        assert patch_result.get("followup_questions") == ["Question B?"]

        # LLM should NOT have been called (no user message to extract from)
        mock_llm.assert_not_called()
        mock_llm_json.assert_not_called()

    def test_second_followup_question_surfaced_on_next_run(self):
        agent = DiscoveryAgent(_make_spec())
        state = _make_state(
            followup_questions=["Question B?"],
            coverage_scores=_all_low_scores(),
        )
        with patch("app.services.llm_service.call_llm"), \
             patch("app.services.llm_service.call_llm_json"):
            patch_result = agent.run(state)

        assert patch_result.get("followup_questions") == []
        open_qs = patch_result.get("open_questions", [])
        assert any("Question B?" in q["question"] for q in open_qs)


# ── Coverage gate triggers discovery_complete ─────────────────────────────────

class TestDiscoveryComplete:

    def test_discovery_complete_set_when_all_scores_above_threshold(self):
        agent = DiscoveryAgent(_make_spec())
        # LLM returns high scores after processing user message
        high_scores_json = json.dumps(_all_high_scores())

        state = _make_state(
            last_user_message="We need SSO and RBAC",
            coverage_scores=_all_low_scores(),
        )

        with patch("app.services.llm_service.call_llm_json") as mock_json:
            # First call: capture_answer → updated_categories
            # Second call: update_coverage → high scores
            mock_json.side_effect = [
                {"updated_categories": {"functional_requirements": {"auth": "SSO, RBAC"}}},
                _all_high_scores(),
            ]
            patch_result = agent.run(state)

        assert patch_result.get("discovery_complete") is True

    def test_discovery_complete_not_set_when_scores_below_threshold(self):
        agent = DiscoveryAgent(_make_spec())
        low_scores = _all_low_scores()
        low_scores["business_context"] = 0.5  # still below

        state = _make_state(
            last_user_message="Some info",
            coverage_scores=_all_low_scores(),
        )

        with patch("app.services.llm_service.call_llm_json") as mock_json, \
             patch("app.services.llm_service.call_llm") as mock_llm:
            mock_json.side_effect = [
                {"updated_categories": {}},
                low_scores,
            ]
            mock_llm.return_value = "What is your business context?"
            patch_result = agent.run(state)

        assert patch_result.get("discovery_complete") is not True


# ── Capture answer and update coverage called ──────────────────────────────────

class TestCaptureAnswerAndCoverage:

    def test_capture_answer_called_when_user_message_present(self):
        agent = DiscoveryAgent(_make_spec())
        state = _make_state(
            last_user_message="We need a CRM for 500 users",
            coverage_scores=_all_low_scores(),
        )

        with patch("app.services.llm_service.call_llm_json") as mock_json, \
             patch("app.services.llm_service.call_llm") as mock_llm:
            mock_json.side_effect = [
                {"updated_categories": {"users_and_scale": {"user_count": "500"}}},
                _all_low_scores(),
            ]
            mock_llm.return_value = "Follow-up question?"
            patch_result = agent.run(state)

        # call_llm_json called at least once (capture_answer + update_coverage)
        assert mock_json.call_count >= 2
        # gathered_requirements updated
        assert "gathered_requirements" in patch_result

    def test_last_user_message_cleared_after_processing(self):
        agent = DiscoveryAgent(_make_spec())
        state = _make_state(
            last_user_message="Some answer",
            coverage_scores=_all_low_scores(),
        )

        with patch("app.services.llm_service.call_llm_json") as mock_json, \
             patch("app.services.llm_service.call_llm") as mock_llm:
            mock_json.side_effect = [{"updated_categories": {}}, _all_low_scores()]
            mock_llm.return_value = "Next question?"
            patch_result = agent.run(state)

        assert patch_result.get("last_user_message") is None


# ── Fallback on LLM failure ────────────────────────────────────────────────────

class TestFallbackOnLlmFailure:

    def test_fallback_question_returned_when_llm_raises(self):
        agent = DiscoveryAgent(_make_spec())
        state = _make_state(coverage_scores=_all_low_scores())

        with patch("app.services.llm_service.call_llm_json") as mock_json, \
             patch("app.services.llm_service.call_llm") as mock_llm:
            mock_llm.side_effect = Exception("API unavailable")
            patch_result = agent.run(state)

        open_qs = patch_result.get("open_questions", [])
        assert len(open_qs) > 0
        # Fallback text contains "requirements"
        assert "requirements" in open_qs[-1]["question"].lower()

    def test_capture_answer_returns_existing_gathered_on_failure(self):
        agent = DiscoveryAgent(_make_spec())
        existing = {"business_context": {"problem": "existing"}}
        state = _make_state(
            last_user_message="Some answer",
            gathered_requirements=existing,
            coverage_scores=_all_low_scores(),
        )

        with patch("app.services.llm_service.call_llm_json") as mock_json, \
             patch("app.services.llm_service.call_llm") as mock_llm:
            # Both LLM calls fail
            mock_json.side_effect = Exception("fail")
            mock_llm.return_value = "A question?"
            patch_result = agent.run(state)

        # gathered_requirements should be unchanged (existing carried forward)
        assert patch_result["gathered_requirements"] == existing


# ── Flat requirements extraction ───────────────────────────────────────────────

class TestFlatRequirementsExtraction:

    def test_list_items_converted_to_flat_requirements(self):
        agent = DiscoveryAgent(_make_spec())
        gathered = {"functional_requirements": ["User can login", "User can export"]}
        items = agent._to_flat_requirements(gathered)
        assert len(items) == 2
        assert all(i["source"] == "discovery" for i in items)
        assert any("login" in i["text"] for i in items)

    def test_dict_items_converted_to_flat_requirements(self):
        agent = DiscoveryAgent(_make_spec())
        gathered = {"users_and_scale": {"user_count": "500 users", "geographies": "UK, US"}}
        items = agent._to_flat_requirements(gathered)
        assert len(items) == 2
        assert any("500 users" in i["text"] for i in items)

    def test_empty_values_skipped(self):
        agent = DiscoveryAgent(_make_spec())
        gathered = {"business_context": {"problem": "", "goals": []}}
        items = agent._to_flat_requirements(gathered)
        assert items == []
