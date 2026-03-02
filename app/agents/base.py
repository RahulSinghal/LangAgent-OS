"""BaseAgent ABC — Phase 1D.

All agents inherit from BaseAgent and implement run().

Constraints enforced by the base class:
  - run() must return a dict (SoT patch).
  - Tool calls must go through self.call_tool() which checks the allowlist.
  - execute() validates and applies the patch before returning new state.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.registry.loader import AgentSpec
from app.sot.patch import apply_patch
from app.sot.state import ProjectState
from app.tools.gateway import ToolResult, execute as gateway_execute


class BaseAgent(ABC):
    """Abstract base for all LangGraph AgentOS agents.

    Subclasses implement run(state) → patch dict.
    The base class handles patch validation, tool routing, and budgets.
    """

    def __init__(self, spec: AgentSpec) -> None:
        self.spec = spec
        self._step_count: int = 0
        self._tool_call_count: int = 0

    # ── Abstract ──────────────────────────────────────────────────────────────

    @abstractmethod
    def run(self, state: ProjectState) -> dict:
        """Execute agent logic and return a SoT patch dict.

        The returned dict may only contain top-level ProjectState field names.
        Unknown keys will cause apply_patch() to raise ValueError.
        """
        ...

    # ── Public API ────────────────────────────────────────────────────────────

    def execute(self, state: ProjectState) -> ProjectState:
        """Full execution pipeline: run → validate patch → apply → return.

        This is the method called by the run engine (not run() directly).

        Returns:
            A new ProjectState with the patch applied.

        Raises:
            ValueError: If the patch is invalid (unknown fields or bad values).
            RuntimeError: If step budget is exceeded.
        """
        if self._step_count >= self.spec.limits.max_steps:
            raise RuntimeError(
                f"{self.spec.name} exceeded max_steps={self.spec.limits.max_steps}"
            )
        self._step_count += 1
        patch = self.run(state)
        return apply_patch(state, patch)

    def call_tool(self, tool_name: str, payload: dict) -> ToolResult:
        """Route a tool call through the gateway with allowlist enforcement.

        Args:
            tool_name: Name of the tool to invoke.
            payload:   Arguments for the tool.

        Returns:
            ToolResult — always returns (never raises), check .success.
        """
        if self._tool_call_count >= self.spec.limits.max_tool_calls:
            return ToolResult(
                success=False,
                error=(
                    f"{self.spec.name} exceeded "
                    f"max_tool_calls={self.spec.limits.max_tool_calls}"
                ),
            )
        self._tool_call_count += 1
        return gateway_execute(
            tool_name=tool_name,
            payload=payload,
            agent_name=self.spec.name,
            allowed_tools=self.spec.allowed_tools,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def reset_counters(self) -> None:
        """Reset step and tool-call counters (useful between test runs)."""
        self._step_count = 0
        self._tool_call_count = 0

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.spec.name!r}>"
