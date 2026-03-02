"""Market evaluation workflow nodes — Phase 2.

Two nodes:

  market_eval_phase  — runs MarketScanAgent, populates SoT market_eval section
  market_eval_gate   — pauses for human approval when decision is BUY or HYBRID

Gate trigger policy (configurable via market_eval.deep_mode in SoT):
  "auto"    — gate never fires; decision is accepted automatically
  "suggest" — gate fires for BUY or HYBRID recommendations (default)
  "off"     — market_eval_phase is skipped; discovery → prd directly

The graph is responsible for honouring DEEP_MODE=off by skipping these nodes.
"""

from __future__ import annotations

from app.sot.patch import apply_patch
from app.sot.state import ApprovalStatus, Phase, ProjectState


# ── market_eval_phase ─────────────────────────────────────────────────────────

def market_eval_phase(state: dict) -> dict:
    """Run MarketScanAgent and update market_eval in SoT.

    Sets current_phase = "market_eval" and populates sot.market_eval.
    """
    from app.agents.market_scan import MarketScanAgent

    sot = ProjectState(**state["sot"])

    agent = MarketScanAgent()
    agent.reset_counters()

    # execute_deep returns DeepWorkOutput; sot_patch contains market_eval
    output = agent.execute_deep(sot)

    patch = {"current_phase": Phase.MARKET_EVAL.value}
    patch.update(output.sot_patch)

    updated_sot = apply_patch(sot, patch)

    return {
        "sot": updated_sot.model_dump_jsonb(),
        "pause_reason": None,
        "bot_response": None,
    }


# ── market_eval_gate ──────────────────────────────────────────────────────────

def market_eval_gate(state: dict) -> dict:
    """Check market_eval decision; pause if human review is needed.

    Gate fires when:
      - deep_mode == "suggest" (default) AND decision in ("buy", "hybrid")

    Gate does NOT fire when:
      - approval already resolved (status == "approved")
      - decision == "build" (safe to proceed automatically)
      - deep_mode == "auto" (automatic acceptance)
      - deep_mode == "off"  (market eval was skipped)
    """
    sot = ProjectState(**state["sot"])
    market_eval = sot.market_eval

    # Already resolved — continue
    me_approval_status = sot.approvals_status.get("market_eval")
    if me_approval_status == ApprovalStatus.APPROVED:
        return {"sot": state["sot"], "pause_reason": None, "bot_response": None}

    # Auto or off mode — proceed without gate
    if market_eval.deep_mode in ("auto", "off"):
        return {"sot": state["sot"], "pause_reason": None, "bot_response": None}

    # "suggest" mode: gate fires for BUY or HYBRID
    decision = (market_eval.decision or market_eval.recommendation or "build").lower()
    if decision in ("buy", "hybrid"):
        approvals = {k: v.value for k, v in sot.approvals_status.items()}
        approvals["market_eval"] = ApprovalStatus.PENDING.value
        updated_sot = apply_patch(sot, {"approvals_status": approvals})
        return {
            "sot": updated_sot.model_dump_jsonb(),
            "pause_reason": "waiting_approval",
            "bot_response": (
                f"Market evaluation recommends **{decision.upper()}** "
                f"(confidence: {market_eval.confidence or 0:.0%}). "
                "Please review the market_eval section and approve or reject."
            ),
        }

    # "build" decision — proceed without gate
    return {"sot": state["sot"], "pause_reason": None, "bot_response": None}
