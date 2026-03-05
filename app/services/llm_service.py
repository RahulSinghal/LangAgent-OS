"""LLM service — thin litellm wrapper for AgentOS agents.

Uses settings.LLM_MODEL (default: gpt-4o) and the provider's API key from settings.
Mirrors Enterprise_bot/app/services/llm.py, adapted to AgentOS settings.

Usage::

    from app.services.llm_service import call_llm, call_llm_json

    text = call_llm(system_prompt, user_message)
    data = call_llm_json(system_prompt, user_message)  # returns dict
"""

from __future__ import annotations

import json
import logging
import time

from app.core.config import settings
from app.core.metrics import LLMUsage, get_run_collector

_log = logging.getLogger(__name__)


def call_llm(
    system_prompt: str,
    user_message: str,
    response_format: str = "text",
) -> str:
    """Call the configured LLM provider via litellm.

    Args:
        system_prompt:   System instructions for the LLM.
        user_message:    The user's message / prompt.
        response_format: "text" for plain text, "json" for JSON object mode.

    Returns:
        The LLM's response as a string (guaranteed non-empty).

    Raises:
        RuntimeError: After exhausting retries on rate-limit errors.
        ValueError:   If the LLM returns an empty response after all retries.
    """
    import litellm  # lazy import — not required when mocked in tests

    provider = (settings.LLM_PROVIDER or "").lower().strip()
    model = settings.LLM_MODEL

    # If using Gemini, prefer litellm's gemini/* model namespace.
    if provider in ("gemini", "google") and "/" not in model:
        model = f"gemini/{model}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    kwargs: dict = {
        "model": model,
        "messages": messages,
    }

    # Pass API key explicitly (keeps behavior consistent across environments)
    api_key: str | None = None
    if provider == "openai":
        api_key = settings.OPENAI_API_KEY or None
    elif provider == "anthropic":
        api_key = settings.ANTHROPIC_API_KEY or None
    elif provider in ("gemini", "google"):
        api_key = settings.GEMINI_API_KEY or settings.GOOGLE_API_KEY or None
    if api_key:
        kwargs["api_key"] = api_key

    if response_format == "json":
        kwargs["response_format"] = {"type": "json_object"}

    max_retries = settings.LLM_MAX_RETRIES
    backoff_base = 2  # seconds; doubles each retry: 2s, 4s, 8s, …

    response = None
    elapsed_ms = 0
    for attempt in range(max_retries + 1):
        started = time.perf_counter()
        try:
            response = litellm.completion(**kwargs)
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            break  # success — exit retry loop
        except litellm.RateLimitError as exc:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            if attempt < max_retries:
                sleep_s = backoff_base * (2 ** attempt)
                _log.warning(
                    "LLM rate-limit hit (attempt %d/%d). Retrying in %ds. error=%s",
                    attempt + 1,
                    max_retries + 1,
                    sleep_s,
                    exc,
                )
                time.sleep(sleep_s)
            else:
                raise RuntimeError(
                    f"LLM rate-limit persisted after {max_retries} retries: {exc}"
                ) from exc

    # Validate response content — guard against None / empty strings.
    content: str | None = None
    if response is not None:
        try:
            content = response.choices[0].message.content
        except (AttributeError, IndexError):
            content = None

    if not content:
        raise ValueError(
            f"LLM returned an empty response (model={model}, "
            f"format={response_format}). Cannot continue."
        )

    # Best-effort metrics capture (used by dashboard/project spend).
    try:
        collector = get_run_collector()
        if collector is not None:
            usage_obj = getattr(response, "usage", None)
            prompt_tokens = 0
            completion_tokens = 0
            total_tokens = 0
            if isinstance(usage_obj, dict):
                prompt_tokens = int(usage_obj.get("prompt_tokens") or 0)
                completion_tokens = int(usage_obj.get("completion_tokens") or 0)
                total_tokens = int(
                    usage_obj.get("total_tokens") or (prompt_tokens + completion_tokens)
                )
            else:
                prompt_tokens = int(getattr(usage_obj, "prompt_tokens", 0) or 0)
                completion_tokens = int(getattr(usage_obj, "completion_tokens", 0) or 0)
                total_tokens = int(
                    getattr(usage_obj, "total_tokens", 0) or (prompt_tokens + completion_tokens)
                )

            cost_usd: float | None = None
            if hasattr(response, "cost"):
                cost_usd = float(getattr(response, "cost") or 0.0)
            else:
                hidden = getattr(response, "_hidden_params", None)
                if isinstance(hidden, dict):
                    maybe_cost = hidden.get("response_cost") or hidden.get("cost")
                    if maybe_cost is not None:
                        cost_usd = float(maybe_cost)

            collector.record_llm_call(
                provider=provider or "unknown",
                model=model,
                latency_ms=elapsed_ms,
                usage=LLMUsage(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                ),
                cost_usd=cost_usd,
            )
    except Exception:
        # Never break product flow due to metrics.
        pass

    return content


def llm_healthcheck() -> tuple[bool, str | None]:
    """Best-effort LLM credential check (low-cost).

    Returns:
        (ok, error_message)
    """
    try:
        _ = call_llm(
            system_prompt="You are a healthcheck endpoint. Reply with 'ok'.",
            user_message="ping",
            response_format="text",
        )
        return True, None
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def call_llm_json(system_prompt: str, user_message: str) -> dict:
    """Call LLM and parse the response as JSON.

    Returns:
        Parsed dict. Returns {} on JSON parse failure (never raises).
    """
    try:
        raw = call_llm(system_prompt, user_message, response_format="json")
    except (RuntimeError, ValueError):
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {}
