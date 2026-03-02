"""Tool Gateway — Phase 1D.

All agent tool calls MUST go through this gateway.
Direct calls from agent code are forbidden.

Public API:
  execute(tool_name, payload, agent_name, allowed_tools, dry_run) -> ToolResult

Phase 1: config-based allowlist, no DB logging.
Phase 2: full policy enforcement, budget tracking, DB logging.
Phase 3: approval-gated tools with preview records.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.tools.local_tools import TOOL_REGISTRY


# ── Schema ────────────────────────────────────────────────────────────────────

class ToolResult(BaseModel):
    success: bool
    output: Any = None
    error: str | None = None


# ── Gateway ───────────────────────────────────────────────────────────────────

def execute(
    tool_name: str,
    payload: dict,
    agent_name: str = "",
    allowed_tools: list[str] | None = None,
    dry_run: bool = False,
) -> ToolResult:
    """Execute a tool through the gateway.

    Args:
        tool_name:     Name of the tool to call.
        payload:       Arguments passed to the tool.
        agent_name:    Name of the calling agent (for logging/policy).
        allowed_tools: Allowlist for this agent. None = no restriction.
        dry_run:       If True, validate and return a preview without executing.

    Returns:
        ToolResult with success flag, output, and optional error message.
    """
    # Phase 1: allowlist check
    if allowed_tools is not None and tool_name not in allowed_tools:
        return ToolResult(
            success=False,
            error=f"Tool '{tool_name}' not in allowlist for agent '{agent_name}'",
        )

    if tool_name not in TOOL_REGISTRY:
        return ToolResult(
            success=False,
            error=f"Unknown tool: '{tool_name}'",
        )

    if dry_run:
        return ToolResult(
            success=True,
            output={"dry_run": True, "tool": tool_name, "payload": payload},
        )

    try:
        result = TOOL_REGISTRY[tool_name](payload)
        return ToolResult(success=True, output=result)
    except Exception as exc:  # noqa: BLE001
        return ToolResult(success=False, error=str(exc))
