from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMCallMetric:
    provider: str
    model: str
    latency_ms: int
    usage: LLMUsage = field(default_factory=LLMUsage)
    cost_usd: float = 0.0


@dataclass
class RunMetricCollector:
    """In-memory metrics accumulator for a single run invocation."""

    llm_calls: list[LLMCallMetric] = field(default_factory=list)

    def record_llm_call(
        self,
        *,
        provider: str,
        model: str,
        latency_ms: int,
        usage: LLMUsage | None = None,
        cost_usd: float | None = None,
    ) -> None:
        self.llm_calls.append(
            LLMCallMetric(
                provider=provider,
                model=model,
                latency_ms=int(latency_ms),
                usage=usage or LLMUsage(),
                cost_usd=float(cost_usd or 0.0),
            )
        )

    def totals(self) -> dict[str, Any]:
        total_tokens = sum(c.usage.total_tokens for c in self.llm_calls)
        total_cost = float(sum(c.cost_usd for c in self.llm_calls))
        total_llm_latency_ms = int(sum(c.latency_ms for c in self.llm_calls))
        calls = len(self.llm_calls)

        by_model: dict[str, dict[str, Any]] = {}
        for c in self.llm_calls:
            key = f"{c.provider}:{c.model}"
            bucket = by_model.setdefault(
                key,
                {
                    "provider": c.provider,
                    "model": c.model,
                    "calls": 0,
                    "tokens": 0,
                    "cost_usd": 0.0,
                    "latency_ms": 0,
                },
            )
            bucket["calls"] += 1
            bucket["tokens"] += int(c.usage.total_tokens)
            bucket["cost_usd"] += float(c.cost_usd)
            bucket["latency_ms"] += int(c.latency_ms)

        return {
            "calls": calls,
            "total_tokens": int(total_tokens),
            "total_cost_usd": float(total_cost),
            "total_llm_latency_ms": int(total_llm_latency_ms),
            "by_model": list(by_model.values()),
        }


_run_collector: ContextVar[RunMetricCollector | None] = ContextVar(
    "run_metric_collector", default=None
)


def set_run_collector(collector: RunMetricCollector | None):
    return _run_collector.set(collector)


def reset_run_collector(token) -> None:
    _run_collector.reset(token)


def get_run_collector() -> RunMetricCollector | None:
    return _run_collector.get()

