"""Unit tests for bug fixes 15–21.

15. Tech-stack compatibility validation
16. CORS wildcard / configurable origins
17. JWT insecure default warning / enforcement
18. Artifact version cleanup
19. LLM health-check endpoint
20. LLM context window trimming
21. GitHub webhook signature verification
"""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────
# Fix 15 — Tech-stack compatibility validation
# ─────────────────────────────────────────────────────────────────

class TestTechStackValidation:
    """Tests for app.services.tech_stack_validation.validate_tech_stack."""

    def _make_tech_stack(self, **kwargs):
        from app.sot.state import TechStackSpec
        return TechStackSpec(**kwargs)

    def test_voice_chatbot_no_telephony_warns(self):
        from app.services.tech_stack_validation import validate_tech_stack
        ts = self._make_tech_stack(telephony=None)
        warnings = validate_tech_stack("voice_chatbot", ts)
        assert any("telephony" in w.lower() for w in warnings)

    def test_voice_chatbot_with_telephony_no_warn(self):
        from app.services.tech_stack_validation import validate_tech_stack
        ts = self._make_tech_stack(telephony="twilio", tts_provider="elevenlabs")
        warnings = validate_tech_stack("voice_chatbot", ts)
        assert not any("telephony" in w.lower() for w in warnings)

    def test_rag_pipeline_no_vector_store_warns(self):
        from app.services.tech_stack_validation import validate_tech_stack
        ts = self._make_tech_stack(vector_store=None)
        warnings = validate_tech_stack("rag_pipeline", ts)
        assert any("vector" in w.lower() for w in warnings)

    def test_rag_pipeline_with_vector_store_no_warn(self):
        from app.services.tech_stack_validation import validate_tech_stack
        ts = self._make_tech_stack(vector_store="pinecone", embedding_model="text-embedding-3-small")
        warnings = validate_tech_stack("rag_pipeline", ts)
        assert not any("vector" in w.lower() for w in warnings)

    def test_crm_no_auth_warns(self):
        from app.services.tech_stack_validation import validate_tech_stack
        ts = self._make_tech_stack(auth_method=None)
        warnings = validate_tech_stack("crm", ts)
        assert any("auth" in w.lower() for w in warnings)

    def test_generic_project_no_warnings(self):
        from app.services.tech_stack_validation import validate_tech_stack
        ts = self._make_tech_stack()
        # generic / unknown project type — no rules defined, no warnings
        warnings = validate_tech_stack("generic", ts)
        assert warnings == []

    def test_returns_list_of_strings(self):
        from app.services.tech_stack_validation import validate_tech_stack
        ts = self._make_tech_stack()
        result = validate_tech_stack("rag_pipeline", ts)
        assert isinstance(result, list)
        for item in result:
            assert isinstance(item, str)

    def test_none_tech_stack_returns_empty(self):
        from app.services.tech_stack_validation import validate_tech_stack
        result = validate_tech_stack("rag_pipeline", None)
        assert result == []


# ─────────────────────────────────────────────────────────────────
# Fix 16 — CORS wildcard / configurable origins
# ─────────────────────────────────────────────────────────────────

class TestCORSOrigins:
    """Tests for Settings.cors_origins computed field."""

    def _make_settings(self, allowed_origins: str):
        from app.core.config import Settings
        return Settings(ALLOWED_ORIGINS=allowed_origins, REQUIRE_SECURE_JWT=False)

    def test_wildcard_string_returns_wildcard_list(self):
        s = self._make_settings("*")
        assert s.cors_origins == ["*"]

    def test_empty_string_returns_wildcard(self):
        s = self._make_settings("")
        assert s.cors_origins == ["*"]

    def test_single_origin_parsed(self):
        s = self._make_settings("https://app.example.com")
        assert s.cors_origins == ["https://app.example.com"]

    def test_multiple_origins_parsed(self):
        s = self._make_settings("https://a.com,https://b.com")
        assert s.cors_origins == ["https://a.com", "https://b.com"]

    def test_origins_trimmed(self):
        s = self._make_settings("  https://a.com ,  https://b.com  ")
        assert s.cors_origins == ["https://a.com", "https://b.com"]

    def test_trailing_comma_ignored(self):
        s = self._make_settings("https://a.com,")
        assert s.cors_origins == ["https://a.com"]


# ─────────────────────────────────────────────────────────────────
# Fix 17 — JWT insecure default warning / enforcement
# ─────────────────────────────────────────────────────────────────

class TestJWTSecretValidation:
    """Tests for Settings._validate_jwt_secret model_validator."""

    def test_default_jwt_warns_not_raises(self, caplog):
        import logging
        from app.core.config import Settings, _INSECURE_JWT_DEFAULT
        with caplog.at_level(logging.WARNING):
            s = Settings(JWT_SECRET_KEY=_INSECURE_JWT_DEFAULT, REQUIRE_SECURE_JWT=False)
        assert s is not None  # Did not raise

    def test_default_jwt_with_require_raises(self):
        from app.core.config import Settings, _INSECURE_JWT_DEFAULT
        with pytest.raises((ValueError, Exception)):
            Settings(JWT_SECRET_KEY=_INSECURE_JWT_DEFAULT, REQUIRE_SECURE_JWT=True)

    def test_custom_jwt_no_error(self):
        from app.core.config import Settings
        s = Settings(JWT_SECRET_KEY="super-secret-random-key-32chars!!", REQUIRE_SECURE_JWT=True)
        assert s is not None

    def test_default_jwt_warning_message(self, caplog):
        import logging
        from app.core.config import Settings, _INSECURE_JWT_DEFAULT
        with caplog.at_level(logging.WARNING, logger="app.core.config"):
            Settings(JWT_SECRET_KEY=_INSECURE_JWT_DEFAULT, REQUIRE_SECURE_JWT=False)
        # Warning should mention the secret and production
        assert any("JWT_SECRET_KEY" in r.message for r in caplog.records)


# ─────────────────────────────────────────────────────────────────
# Fix 18 — Artifact version cleanup
# ─────────────────────────────────────────────────────────────────

class TestArtifactVersionCleanup:
    """Tests for artifacts.cleanup_old_artifact_versions."""

    def _make_artifact(self, id: int, file_path: str | None = None):
        a = MagicMock()
        a.id = id
        a.file_path = file_path
        return a

    def test_no_excess_versions_returns_zero(self):
        from app.services.artifacts import cleanup_old_artifact_versions
        db = MagicMock()
        # Only 3 versions, keep=5 → nothing to delete
        versions = [self._make_artifact(i) for i in range(3, 0, -1)]
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = versions
        deleted = cleanup_old_artifact_versions(db, project_id=1, artifact_type="prd", keep=5)
        assert deleted == 0
        db.commit.assert_not_called()

    def test_excess_versions_deleted(self, tmp_path):
        from app.services.artifacts import cleanup_old_artifact_versions
        # Create real temp files to test unlink
        files = []
        for i in range(5):
            f = tmp_path / f"v{i+1}.md"
            f.write_text("content")
            files.append(str(f))

        db = MagicMock()
        versions = [self._make_artifact(5 - i, files[4 - i]) for i in range(5)]
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = versions

        deleted = cleanup_old_artifact_versions(db, project_id=1, artifact_type="prd", keep=3)
        assert deleted == 2
        db.commit.assert_called_once()

    def test_keep_zero_disables_cleanup(self):
        from app.services.artifacts import cleanup_old_artifact_versions
        db = MagicMock()
        deleted = cleanup_old_artifact_versions(db, project_id=1, artifact_type="prd", keep=0)
        assert deleted == 0
        db.query.assert_not_called()

    def test_file_not_found_does_not_raise(self, tmp_path):
        from app.services.artifacts import cleanup_old_artifact_versions
        db = MagicMock()
        # file_path points to a non-existent file
        versions = [self._make_artifact(2, "/nonexistent/path/v2.md"),
                    self._make_artifact(1, "/nonexistent/path/v1.md")]
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = versions
        # Should not raise even though files are missing
        deleted = cleanup_old_artifact_versions(db, project_id=1, artifact_type="prd", keep=1)
        assert deleted == 1

    def test_uses_settings_default_when_keep_is_none(self):
        from app.services.artifacts import cleanup_old_artifact_versions
        from app.core.config import settings
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
        cleanup_old_artifact_versions(db, project_id=1, artifact_type="prd", keep=None)
        # Just verify it didn't raise — keep defaults to settings.ARTIFACT_MAX_VERSIONS
        assert settings.ARTIFACT_MAX_VERSIONS > 0


# ─────────────────────────────────────────────────────────────────
# Fix 19 — LLM health-check endpoint
# ─────────────────────────────────────────────────────────────────

class TestLLMHealthEndpoint:
    """Tests for GET /health/llm endpoint."""

    def test_health_ok_when_llm_responds(self):
        from fastapi.testclient import TestClient
        from app.main import app

        with patch("app.services.llm_service.call_llm", return_value="ok"):
            client = TestClient(app)
            resp = client.get("/health/llm")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["error"] is None

    def test_health_error_when_llm_fails(self):
        from fastapi.testclient import TestClient
        from app.main import app

        with patch("app.services.llm_service.call_llm", side_effect=RuntimeError("no API key")):
            client = TestClient(app)
            resp = client.get("/health/llm")
        assert resp.status_code == 200  # endpoint itself succeeds
        data = resp.json()
        assert data["status"] == "error"
        assert "no API key" in data["error"]

    def test_health_response_has_model_field(self):
        from fastapi.testclient import TestClient
        from app.main import app

        with patch("app.services.llm_service.call_llm", return_value="ok"):
            client = TestClient(app)
            resp = client.get("/health/llm")
        data = resp.json()
        assert "model" in data


# ─────────────────────────────────────────────────────────────────
# Fix 20 — LLM context window trimming
# ─────────────────────────────────────────────────────────────────

class TestLLMContextTrimming:
    """Tests for _trim_to_budget and call_llm context trimming."""

    def test_trim_short_text_unchanged(self):
        from app.services.llm_service import _trim_to_budget
        text = "Hello, world!"
        assert _trim_to_budget(text, 1000) == text

    def test_trim_long_text_fits_budget(self):
        from app.services.llm_service import _trim_to_budget
        text = "A" * 10_000
        result = _trim_to_budget(text, 500)
        assert len(result) <= 500

    def test_trim_keeps_start_and_end(self):
        from app.services.llm_service import _trim_to_budget
        start = "START" * 100
        end = "END" * 100
        text = start + "MIDDLE" * 1000 + end
        result = _trim_to_budget(text, 500)
        assert result.startswith("START")
        assert result.endswith("END")

    def test_trim_inserts_marker(self):
        from app.services.llm_service import _trim_to_budget
        text = "X" * 5000
        result = _trim_to_budget(text, 1000)
        assert "trimmed" in result.lower() or "…" in result

    def test_call_llm_trims_when_over_budget(self):
        """call_llm should trim user_message if it exceeds LLM_CONTEXT_MAX_CHARS."""
        from app.services.llm_service import call_llm

        captured = {}

        def fake_completion(**kwargs):
            captured["messages"] = kwargs["messages"]
            msg = SimpleNamespace(content="ok")
            choice = SimpleNamespace(message=msg)
            return SimpleNamespace(choices=[choice], usage=None, _hidden_params={})

        long_msg = "X" * 100_000

        with patch("litellm.completion", side_effect=fake_completion), \
             patch("app.services.llm_service.settings") as mock_settings:
            mock_settings.LLM_PROVIDER = "openai"
            mock_settings.LLM_MODEL = "gpt-4o"
            mock_settings.OPENAI_API_KEY = "test-key"
            mock_settings.ANTHROPIC_API_KEY = ""
            mock_settings.GEMINI_API_KEY = ""
            mock_settings.GOOGLE_API_KEY = ""
            mock_settings.LLM_CONTEXT_MAX_CHARS = 1000
            mock_settings.LLM_MAX_RETRIES = 0

            call_llm("sys", long_msg)

        user_content = captured["messages"][1]["content"]
        assert len(user_content) <= 1000

    def test_call_llm_no_trim_when_within_budget(self):
        """call_llm should not trim user_message if it fits in the budget."""
        from app.services.llm_service import call_llm

        captured = {}

        def fake_completion(**kwargs):
            captured["messages"] = kwargs["messages"]
            msg = SimpleNamespace(content="ok")
            choice = SimpleNamespace(message=msg)
            return SimpleNamespace(choices=[choice], usage=None, _hidden_params={})

        short_msg = "Hello!"

        with patch("litellm.completion", side_effect=fake_completion), \
             patch("app.services.llm_service.settings") as mock_settings:
            mock_settings.LLM_PROVIDER = "openai"
            mock_settings.LLM_MODEL = "gpt-4o"
            mock_settings.OPENAI_API_KEY = "test-key"
            mock_settings.ANTHROPIC_API_KEY = ""
            mock_settings.GEMINI_API_KEY = ""
            mock_settings.GOOGLE_API_KEY = ""
            mock_settings.LLM_CONTEXT_MAX_CHARS = 40_000
            mock_settings.LLM_MAX_RETRIES = 0

            call_llm("sys", short_msg)

        user_content = captured["messages"][1]["content"]
        assert user_content == short_msg


# ─────────────────────────────────────────────────────────────────
# Fix 21 — GitHub webhook signature verification
# ─────────────────────────────────────────────────────────────────

class TestGitHubWebhookSignature:
    """Tests for _verify_signature in routes_github_webhook.py."""

    def _make_signature(self, secret: str, payload: bytes) -> str:
        digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        return f"sha256={digest}"

    def test_valid_signature_accepted(self):
        from app.api.routes_github_webhook import _verify_signature
        payload = b'{"action": "test"}'
        secret = "my-webhook-secret"
        sig = self._make_signature(secret, payload)
        with patch("app.api.routes_github_webhook.settings") as mock_settings:
            mock_settings.GITHUB_WEBHOOK_SECRET = secret
            # Should not raise
            _verify_signature(payload, sig)

    def test_invalid_signature_raises_401(self):
        from fastapi import HTTPException
        from app.api.routes_github_webhook import _verify_signature
        payload = b'{"action": "test"}'
        with patch("app.api.routes_github_webhook.settings") as mock_settings:
            mock_settings.GITHUB_WEBHOOK_SECRET = "correct-secret"
            with pytest.raises(HTTPException) as exc_info:
                _verify_signature(payload, "sha256=badhash")
        assert exc_info.value.status_code == 401

    def test_empty_secret_skips_verification(self):
        from app.api.routes_github_webhook import _verify_signature
        payload = b'{"action": "test"}'
        with patch("app.api.routes_github_webhook.settings") as mock_settings:
            mock_settings.GITHUB_WEBHOOK_SECRET = ""
            # No secret configured → skip verification, no exception
            _verify_signature(payload, "sha256=anything")

    def test_tampered_payload_rejected(self):
        from fastapi import HTTPException
        from app.api.routes_github_webhook import _verify_signature
        original_payload = b'{"action": "original"}'
        tampered_payload = b'{"action": "tampered"}'
        secret = "webhook-secret"
        sig = self._make_signature(secret, original_payload)
        with patch("app.api.routes_github_webhook.settings") as mock_settings:
            mock_settings.GITHUB_WEBHOOK_SECRET = secret
            with pytest.raises(HTTPException) as exc_info:
                _verify_signature(tampered_payload, sig)
        assert exc_info.value.status_code == 401

    def test_webhook_endpoint_returns_204_on_valid_payload(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.core.config import settings as real_settings

        payload = json.dumps({"action": "completed", "check_run": {"name": "ci", "conclusion": "success", "app": {"slug": "github-actions"}, "check_suite": {"head_sha": "abc123"}}}).encode()
        secret = "test-secret"
        sig = self._make_signature(secret, payload)
        webhook_url = f"{real_settings.API_PREFIX}/github/webhook"

        with patch("app.api.routes_github_webhook.settings") as mock_settings:
            mock_settings.GITHUB_WEBHOOK_SECRET = secret
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                webhook_url,
                content=payload,
                headers={
                    "X-GitHub-Event": "check_run",
                    "X-Hub-Signature-256": sig,
                    "Content-Type": "application/json",
                },
            )
        # 204 No Content on success
        assert resp.status_code in (204, 200)

    def test_webhook_missing_signature_when_secret_set(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.core.config import settings as real_settings

        payload = b'{"action": "push"}'
        webhook_url = f"{real_settings.API_PREFIX}/github/webhook"

        with patch("app.api.routes_github_webhook.settings") as mock_settings:
            mock_settings.GITHUB_WEBHOOK_SECRET = "required-secret"
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                webhook_url,
                content=payload,
                headers={
                    "X-GitHub-Event": "push",
                    "Content-Type": "application/json",
                    # No X-Hub-Signature-256 header
                },
            )
        assert resp.status_code in (401, 422)
