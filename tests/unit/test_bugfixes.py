"""Unit tests for all Critical and High/Medium-Reliability bug fixes.

Covers:
  - Concurrent run locking (SELECT FOR UPDATE in resume_run)
  - Infinite rejection loop circuit breaker (approval_gate)
  - LLM rate-limit retry + empty-response validation (llm_service)
  - Prompt injection sanitization (_sanitize_user_input)
  - File upload size limit (routes_documents)
  - Malformed agent patch error handling (workflow nodes)
"""

from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_completion_response(content: str) -> MagicMock:
    """Build a mock litellm completion response."""
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = None
    return resp


def _make_sot_dict(**overrides) -> dict:
    """Return a minimal valid SoT dict for gate tests."""
    from app.sot.state import create_initial_state
    sot = create_initial_state(project_id=1, run_id=1)
    d = sot.model_dump(mode="json")
    d.update(overrides)
    return d


# ─────────────────────────────────────────────────────────────────────────────
# 1. Prompt injection sanitization
# ─────────────────────────────────────────────────────────────────────────────

class TestSanitizeUserInput:
    """Tests for _sanitize_user_input in app.services.runs."""

    def _fn(self):
        from app.services.runs import _sanitize_user_input
        return _sanitize_user_input

    def test_none_returns_none(self):
        assert self._fn()(None) is None

    def test_normal_text_unchanged(self):
        assert self._fn()("hello world") == "hello world"

    def test_newline_and_tab_preserved(self):
        text = "line1\nline2\ttabbed"
        assert self._fn()(text) == text

    def test_null_byte_stripped(self):
        assert self._fn()("abc\x00def") == "abcdef"

    def test_control_chars_stripped(self):
        # \x01-\x08 and \x0e-\x1f should be removed; \t \n \r kept
        text = "\x01\x02hello\x1fworld\x7f"
        assert self._fn()(text) == "helloworld"

    def test_unicode_preserved(self):
        text = "こんにちは 🎉 ñoño"
        assert self._fn()(text) == text

    def test_truncates_to_max_length(self):
        from app.core.config import settings
        max_len = settings.MAX_USER_MESSAGE_LENGTH
        long_text = "a" * (max_len + 500)
        result = self._fn()(long_text)
        assert len(result) == max_len

    def test_exactly_at_max_length_not_truncated(self):
        from app.core.config import settings
        max_len = settings.MAX_USER_MESSAGE_LENGTH
        text = "b" * max_len
        assert self._fn()(text) == text


# ─────────────────────────────────────────────────────────────────────────────
# 2. LLM rate-limit retry + empty response validation
# ─────────────────────────────────────────────────────────────────────────────

class TestCallLlmRetry:
    """Tests for retry logic and empty-response guard in call_llm."""

    def test_empty_response_raises_value_error(self):
        from app.services.llm_service import call_llm
        with patch("litellm.completion", return_value=_make_completion_response("")):
            with pytest.raises(ValueError, match="empty response"):
                call_llm("sys", "user")

    def test_none_content_raises_value_error(self):
        from app.services.llm_service import call_llm
        resp = _make_completion_response("placeholder")
        resp.choices[0].message.content = None
        with patch("litellm.completion", return_value=resp):
            with pytest.raises(ValueError, match="empty response"):
                call_llm("sys", "user")

    def test_rate_limit_retries_and_succeeds(self):
        import litellm
        from app.services.llm_service import call_llm

        side_effects = [
            litellm.RateLimitError("rate limit", llm_provider="openai", model="gpt-4o"),
            _make_completion_response("ok after retry"),
        ]
        with patch("litellm.completion", side_effect=side_effects):
            with patch("time.sleep"):  # skip actual sleep
                result = call_llm("sys", "user")
        assert result == "ok after retry"

    def test_rate_limit_exhausted_raises_runtime_error(self):
        import litellm
        from app.services.llm_service import call_llm
        from app.core.config import settings

        err = litellm.RateLimitError("rate limit", llm_provider="openai", model="gpt-4o")
        # Always raise — exhaust all retries
        side_effects = [err] * (settings.LLM_MAX_RETRIES + 1)
        with patch("litellm.completion", side_effect=side_effects):
            with patch("time.sleep"):
                with pytest.raises(RuntimeError, match="rate-limit persisted"):
                    call_llm("sys", "user")

    def test_non_rate_limit_error_not_retried(self):
        """Other exceptions bubble up immediately without retrying."""
        from app.services.llm_service import call_llm

        call_count = 0

        def boom(**kwargs):
            nonlocal call_count
            call_count += 1
            raise ConnectionError("network down")

        with patch("litellm.completion", side_effect=boom):
            with pytest.raises(ConnectionError):
                call_llm("sys", "user")

        assert call_count == 1  # no retry

    def test_call_llm_json_returns_empty_on_empty_response(self):
        """call_llm_json should catch ValueError and return {}."""
        from app.services.llm_service import call_llm_json
        with patch("litellm.completion", return_value=_make_completion_response("")):
            result = call_llm_json("sys", "user")
        assert result == {}


# ─────────────────────────────────────────────────────────────────────────────
# 3. Infinite rejection loop circuit breaker
# ─────────────────────────────────────────────────────────────────────────────

class TestRejectionCircuitBreaker:
    """Tests for MAX_REJECTION_RETRIES guard in _gate()."""

    def _rejected_state(self, artifact_type: str, count: int) -> dict:
        """Build a state dict where artifact_type is rejected N times."""
        sot_dict = _make_sot_dict(
            approvals_status={artifact_type: "rejected"},
            rejection_counts={artifact_type: count},
        )
        return {"sot": sot_dict, "run_id": 99}

    def test_first_rejection_routes_back(self):
        from app.workflow.nodes.approval_gate import _gate
        from app.core.config import settings

        with patch("app.workflow.nodes.approval_gate._load_rejection_comment", return_value="fix it"):
            result = _gate(self._rejected_state("prd", 0), "prd")

        # Should route back (no pause) with feedback
        assert result["pause_reason"] is None
        sot = result["sot"]
        assert sot["rejection_counts"]["prd"] == 1

    def test_rejection_count_increments(self):
        from app.workflow.nodes.approval_gate import _gate

        with patch("app.workflow.nodes.approval_gate._load_rejection_comment", return_value=""):
            result = _gate(self._rejected_state("sow", 1), "sow")

        assert result["sot"]["rejection_counts"]["sow"] == 2

    def test_circuit_breaker_triggers_at_max(self):
        from app.workflow.nodes.approval_gate import _gate
        from app.core.config import settings

        max_r = settings.MAX_REJECTION_RETRIES
        # count is already at max — next rejection exceeds limit
        with patch("app.workflow.nodes.approval_gate._load_rejection_comment", return_value=""):
            with pytest.raises(RuntimeError, match="rejected"):
                _gate(self._rejected_state("prd", max_r), "prd")

    def test_circuit_breaker_not_triggered_below_max(self):
        from app.workflow.nodes.approval_gate import _gate
        from app.core.config import settings

        max_r = settings.MAX_REJECTION_RETRIES
        # count is one below max — should still route back
        with patch("app.workflow.nodes.approval_gate._load_rejection_comment", return_value=""):
            result = _gate(self._rejected_state("prd", max_r - 1), "prd")

        assert result["pause_reason"] is None

    def test_approved_state_passes_through(self):
        from app.workflow.nodes.approval_gate import _gate

        sot_dict = _make_sot_dict(approvals_status={"prd": "approved"})
        result = _gate({"sot": sot_dict, "run_id": 1}, "prd")

        assert result["pause_reason"] is None
        assert result["bot_response"] is None

    def test_pending_state_sets_waiting_approval(self):
        from app.workflow.nodes.approval_gate import _gate

        sot_dict = _make_sot_dict(approvals_status={})
        result = _gate({"sot": sot_dict, "run_id": 1}, "prd")

        assert result["pause_reason"] == "waiting_approval"


# ─────────────────────────────────────────────────────────────────────────────
# 4. rejection_counts field in ProjectState
# ─────────────────────────────────────────────────────────────────────────────

class TestRejectionCountsField:
    """Ensure the new rejection_counts field works correctly in ProjectState."""

    def test_default_is_empty_dict(self):
        from app.sot.state import ProjectState
        s = ProjectState(project_id=1)
        assert s.rejection_counts == {}

    def test_patch_sets_rejection_counts(self):
        from app.sot.state import ProjectState
        from app.sot.patch import apply_patch
        s = ProjectState(project_id=1)
        new_s = apply_patch(s, {"rejection_counts": {"prd": 2}})
        assert new_s.rejection_counts == {"prd": 2}

    def test_serialized_and_deserialized(self):
        from app.sot.state import ProjectState
        s = ProjectState(project_id=1, rejection_counts={"sow": 1, "prd": 3})
        d = s.model_dump_jsonb()
        s2 = ProjectState(**d)
        assert s2.rejection_counts == {"sow": 1, "prd": 3}


# ─────────────────────────────────────────────────────────────────────────────
# 5. File upload size limit
# ─────────────────────────────────────────────────────────────────────────────

class TestFileUploadSizeLimit:
    """Tests for MAX_UPLOAD_SIZE_BYTES check in /documents/extract."""

    def _make_upload_file(self, data: bytes, filename: str = "test.txt", content_type: str = "text/plain"):
        mock_file = MagicMock()
        mock_file.filename = filename
        mock_file.content_type = content_type
        mock_file.read = MagicMock(return_value=data)
        # Make it awaitable
        import asyncio
        mock_file.read = MagicMock(return_value=asyncio.coroutine(lambda: data)())
        return mock_file

    @pytest.mark.asyncio
    async def test_file_within_limit_accepted(self):
        from app.api.routes_documents import extract_document_text
        from app.core.config import settings

        small_data = b"hello world"
        assert len(small_data) < settings.MAX_UPLOAD_SIZE_BYTES

        file = MagicMock()
        file.filename = "small.txt"
        file.content_type = "text/plain"

        async def _read():
            return small_data
        file.read = _read

        result = await extract_document_text(file=file)
        assert result["text"] == "hello world"

    @pytest.mark.asyncio
    async def test_file_over_limit_returns_413(self):
        from fastapi import HTTPException
        from app.api.routes_documents import extract_document_text
        from app.core.config import settings

        # Use patch to set a small limit
        with patch.object(settings, "MAX_UPLOAD_SIZE_BYTES", 10):
            large_data = b"x" * 100  # 100 bytes > 10 byte limit

            file = MagicMock()
            file.filename = "large.pdf"
            file.content_type = "application/pdf"

            async def _read():
                return large_data
            file.read = _read

            with pytest.raises(HTTPException) as exc_info:
                await extract_document_text(file=file)

        assert exc_info.value.status_code == 413

    @pytest.mark.asyncio
    async def test_size_check_disabled_when_zero(self):
        """MAX_UPLOAD_SIZE_BYTES=0 disables the size check."""
        from app.api.routes_documents import extract_document_text
        from app.core.config import settings

        with patch.object(settings, "MAX_UPLOAD_SIZE_BYTES", 0):
            data = b"a" * 1000

            file = MagicMock()
            file.filename = "big.txt"
            file.content_type = "text/plain"

            async def _read():
                return data
            file.read = _read

            result = await extract_document_text(file=file)
        assert result["text"] == "a" * 1000


# ─────────────────────────────────────────────────────────────────────────────
# 6. Concurrent run locking — resume_run raises on already-running
# ─────────────────────────────────────────────────────────────────────────────

class TestConcurrentRunLocking:
    """Tests that resume_run raises when a run is already status=running."""

    def _mock_db_with_run(self, status: str):
        """Return a mock SQLAlchemy session with a Run of given status."""
        run = MagicMock()
        run.id = 1
        run.status = status
        run.project_id = 1
        run.session_id = None

        db = MagicMock()
        # with_for_update().filter().first() chain
        db.query.return_value.with_for_update.return_value.filter.return_value.first.return_value = run
        db.get.return_value = run
        return db, run

    def test_resume_raises_if_already_running(self):
        from app.services.runs import resume_run

        db, run = self._mock_db_with_run(status="running")

        with pytest.raises(ValueError, match="already being processed"):
            resume_run(db, run_id=1, user_message="hello")

    def test_resume_uses_with_for_update(self):
        """Verify that resume_run calls with_for_update() on the query."""
        from app.services.runs import resume_run

        db, run = self._mock_db_with_run(status="waiting_user")

        # Lazy import inside resume_run — patch at source module.
        with patch("app.services.snapshots.load_latest_snapshot", return_value=None):
            with pytest.raises(ValueError, match="No snapshot"):
                resume_run(db, run_id=1, user_message="hi")

        # Verify with_for_update was called
        db.query.return_value.with_for_update.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# 7. Malformed agent patch — run marked 'error'
# ─────────────────────────────────────────────────────────────────────────────

class TestMalformedPatchErrorHandling:
    """Tests that ValueError from bad agent patches is re-raised by nodes,
    and that runs.py catches it and marks the run as 'error'."""

    def test_prd_phase_reraises_value_error(self):
        from app.workflow.nodes.prd import prd_phase
        from app.sot.state import create_initial_state

        sot = create_initial_state(project_id=1, run_id=1)
        state = {"sot": sot.model_dump_jsonb(), "run_id": 1}

        bad_agent = MagicMock()
        bad_agent.execute.side_effect = ValueError("unknown field: 'bad_field'")

        with patch("app.workflow.nodes.prd.MockPRDAgent", return_value=bad_agent):
            with patch("app.workflow.nodes.prd.use_mock_agents", return_value=True):
                with pytest.raises(ValueError, match="unknown field"):
                    prd_phase(state)

    def test_sow_phase_reraises_value_error(self):
        from app.workflow.nodes.sow import sow_phase
        from app.sot.state import create_initial_state

        sot = create_initial_state(project_id=1, run_id=1)
        state = {"sot": sot.model_dump_jsonb(), "run_id": 1}

        bad_agent = MagicMock()
        bad_agent.execute.side_effect = ValueError("bad patch")

        with patch("app.workflow.nodes.sow.MockSOWAgent", return_value=bad_agent):
            with patch("app.workflow.nodes.sow.use_mock_agents", return_value=True):
                with pytest.raises(ValueError, match="bad patch"):
                    sow_phase(state)

    def test_coding_milestone_reraises_value_error(self):
        from app.workflow.nodes.coding_milestone import coding_milestone_phase
        from app.sot.state import create_initial_state, MilestoneItem

        sot = create_initial_state(project_id=1, run_id=1)
        ms = MilestoneItem(name="Auth", description="auth system")
        from app.sot.patch import apply_patch
        sot = apply_patch(sot, {"coding_plan": [ms.model_dump()]})
        state = {"sot": sot.model_dump_jsonb(), "run_id": 1}

        bad_agent = MagicMock()
        bad_agent.execute.side_effect = ValueError("bad code patch")

        with patch("app.workflow.nodes.coding_milestone.MockMilestoneCodeAgent", return_value=bad_agent):
            with patch("app.workflow.nodes.coding_milestone.use_mock_agents", return_value=True):
                with pytest.raises(ValueError, match="bad code patch"):
                    coding_milestone_phase(state)

    def test_start_run_marks_error_on_workflow_exception(self):
        """start_run must set run.status='error' when the workflow raises."""
        from app.services.runs import start_run

        run_mock = MagicMock()
        run_mock.id = 42
        run_mock.project_id = 1
        run_mock.session_id = None

        db = MagicMock()

        # Lazy imports inside start_run — patch at source modules.
        with patch("app.services.runs.create_run", return_value=run_mock), \
             patch("app.sot.state.create_initial_state") as mock_state, \
             patch("app.workflow.graph.get_workflow") as mock_wf, \
             patch("app.services.runs.update_run_status") as mock_update, \
             patch("app.core.metrics.set_run_collector"), \
             patch("app.core.metrics.reset_run_collector"), \
             patch("app.core.metrics.RunMetricCollector"):

            initial_sot = MagicMock()
            initial_sot.model_dump_jsonb.return_value = {}
            mock_state.return_value = initial_sot
            mock_wf.return_value.invoke.side_effect = RuntimeError("workflow exploded")

            with pytest.raises(RuntimeError, match="workflow exploded"):
                start_run(db, project_id=1, user_message="hi")

            # Must have marked run as error
            mock_update.assert_called_with(db, 42, status="error")


# ─────────────────────────────────────────────────────────────────────────────
# 8. Config: new settings exist with expected defaults
# ─────────────────────────────────────────────────────────────────────────────

class TestNewConfigSettings:

    def test_llm_max_retries_default(self):
        from app.core.config import settings
        assert settings.LLM_MAX_RETRIES == 3

    def test_max_rejection_retries_default(self):
        from app.core.config import settings
        assert settings.MAX_REJECTION_RETRIES == 3

    def test_max_upload_size_bytes_default(self):
        from app.core.config import settings
        assert settings.MAX_UPLOAD_SIZE_BYTES == 20 * 1024 * 1024

    def test_max_user_message_length_default(self):
        from app.core.config import settings
        assert settings.MAX_USER_MESSAGE_LENGTH == 10_000
