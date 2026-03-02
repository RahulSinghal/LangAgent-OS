"""Unit tests for app/services/llm_service.py — Phase 4.

All litellm.completion calls are mocked — no API key required.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


# ── helpers ────────────────────────────────────────────────────────────────────

def _make_completion_response(content: str) -> MagicMock:
    """Build a mock litellm completion response."""
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


# ── call_llm ──────────────────────────────────────────────────────────────────

class TestCallLlm:

    def test_returns_plain_string(self):
        from app.services.llm_service import call_llm
        with patch("litellm.completion", return_value=_make_completion_response("hello")) as mock:
            result = call_llm("sys", "user")
        assert result == "hello"

    def test_passes_system_and_user_message(self):
        from app.services.llm_service import call_llm
        with patch("litellm.completion", return_value=_make_completion_response("ok")) as mock:
            call_llm("system prompt", "user prompt")
        call_kwargs = mock.call_args
        messages = call_kwargs.kwargs.get("messages") or call_kwargs.args[0]
        # messages is a keyword arg
        msgs = mock.call_args.kwargs["messages"]
        assert msgs[0] == {"role": "system", "content": "system prompt"}
        assert msgs[1] == {"role": "user", "content": "user prompt"}

    def test_text_mode_does_not_set_response_format(self):
        from app.services.llm_service import call_llm
        with patch("litellm.completion", return_value=_make_completion_response("ok")) as mock:
            call_llm("sys", "user", response_format="text")
        kwargs = mock.call_args.kwargs
        assert "response_format" not in kwargs

    def test_json_mode_sets_response_format(self):
        from app.services.llm_service import call_llm
        with patch("litellm.completion", return_value=_make_completion_response("{}")) as mock:
            call_llm("sys", "user", response_format="json")
        kwargs = mock.call_args.kwargs
        assert kwargs.get("response_format") == {"type": "json_object"}

    def test_uses_settings_llm_model(self):
        from app.services.llm_service import call_llm
        from app.core.config import settings
        with patch("litellm.completion", return_value=_make_completion_response("ok")) as mock:
            call_llm("sys", "user")
        kwargs = mock.call_args.kwargs
        assert kwargs["model"] == settings.LLM_MODEL


# ── call_llm_json ─────────────────────────────────────────────────────────────

class TestCallLlmJson:

    def test_parses_json_response(self):
        from app.services.llm_service import call_llm_json
        payload = {"key": "value", "count": 42}
        with patch("litellm.completion", return_value=_make_completion_response(json.dumps(payload))):
            result = call_llm_json("sys", "user")
        assert result == payload

    def test_returns_empty_dict_on_invalid_json(self):
        from app.services.llm_service import call_llm_json
        with patch("litellm.completion", return_value=_make_completion_response("not json")):
            result = call_llm_json("sys", "user")
        assert result == {}

    def test_returns_empty_dict_on_empty_response(self):
        from app.services.llm_service import call_llm_json
        with patch("litellm.completion", return_value=_make_completion_response("")):
            result = call_llm_json("sys", "user")
        assert result == {}

    def test_nested_dict_parsed_correctly(self):
        from app.services.llm_service import call_llm_json
        payload = {"updated_categories": {"business_context": {"problem": "x"}}}
        with patch("litellm.completion", return_value=_make_completion_response(json.dumps(payload))):
            result = call_llm_json("sys", "user")
        assert result["updated_categories"]["business_context"]["problem"] == "x"
