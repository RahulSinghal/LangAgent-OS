"""Runtime state for AgentOS.

Used to expose:
- effective agent mode (real vs mock) based on env + LLM availability
- LLM key presence/validity status for UI display
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.core.config import settings


AgentMode = Literal["real", "mock"]
KeyValidity = Literal["valid", "invalid", "unknown", "missing"]


@dataclass
class RuntimeStatus:
    agent_mode: AgentMode = "mock"
    llm_provider: str = ""
    llm_model: str = ""
    llm_key_present: bool = False
    llm_key_validity: KeyValidity = "unknown"
    reason: str = ""
    checked: bool = False


_status = RuntimeStatus()


def _provider_key() -> str:
    p = (settings.LLM_PROVIDER or "").lower().strip()
    if p == "openai":
        return settings.OPENAI_API_KEY or ""
    if p == "anthropic":
        return settings.ANTHROPIC_API_KEY or ""
    if p in ("gemini", "google"):
        return settings.GEMINI_API_KEY or settings.GOOGLE_API_KEY or ""
    return ""


def refresh_runtime_status(validate_llm: bool = True) -> RuntimeStatus:
    """Compute effective mode and (optionally) validate LLM credentials."""
    global _status

    provider = (settings.LLM_PROVIDER or "").strip()
    model = (settings.LLM_MODEL or "").strip()
    key = _provider_key()
    key_present = bool(key.strip())

    # Hard override: explicit USE_MOCK_AGENTS env always wins.
    if settings.USE_MOCK_AGENTS:
        _status = RuntimeStatus(
            agent_mode="mock",
            llm_provider=provider,
            llm_model=model,
            llm_key_present=key_present,
            llm_key_validity="unknown" if key_present else "missing",
            reason="USE_MOCK_AGENTS=true",
            checked=True,
        )
        return _status

    # No key → mock
    if not key_present:
        _status = RuntimeStatus(
            agent_mode="mock",
            llm_provider=provider,
            llm_model=model,
            llm_key_present=False,
            llm_key_validity="missing",
            reason="No LLM API key configured",
            checked=True,
        )
        return _status

    # Key present → attempt validation (optional)
    validity: KeyValidity = "unknown"
    reason = "LLM key present"
    if validate_llm:
        try:
            from app.services.llm_service import llm_healthcheck

            ok, err = llm_healthcheck()
            validity = "valid" if ok else "invalid"
            reason = "LLM validated" if ok else f"LLM validation failed: {err}"
        except Exception as exc:  # noqa: BLE001
            validity = "unknown"
            reason = f"LLM validation error: {exc}"

    agent_mode: AgentMode = "real" if validity in ("valid", "unknown") else "mock"
    if agent_mode == "mock" and validity == "invalid":
        reason = reason or "Invalid LLM key"

    _status = RuntimeStatus(
        agent_mode=agent_mode,
        llm_provider=provider,
        llm_model=model,
        llm_key_present=True,
        llm_key_validity=validity,
        reason=reason,
        checked=True,
    )
    return _status


def get_runtime_status() -> RuntimeStatus:
    if not _status.checked:
        refresh_runtime_status(validate_llm=False)
    return _status


def use_mock_agents() -> bool:
    return get_runtime_status().agent_mode == "mock"

