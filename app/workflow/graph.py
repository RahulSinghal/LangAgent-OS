"""LangGraph workflow graph — Phase 4.

Graph structure (Phase 4):

  [conditional_entry_point] ─── routes to right node based on current_phase
        │
        ├─ intake  →  discovery  →  [pause→END | continue→market_eval]
        │
        ├─ market_eval → market_eval_gate → [waiting→END | approved→prd]
        │
        ├─ prd    →  prd_gate   →  [waiting→END | rejected→prd | approved→commercials]
        │
        ├─ commercials → commercials_gate → [waiting→END | rejected→commercials | approved→sow]
        │
        ├─ sow    →  sow_gate   →  [waiting→END | rejected→sow | approved→end]
        │
        └─ end    →  END

Pause / Resume:
  - start_run:   invokes from entry point; may pause at discovery, a gate, or end.
  - resume_run:  loads latest SoT snapshot, re-invokes; entry router jumps to
                 the correct node based on current_phase.

WorkflowState is the dict threaded through every LangGraph node.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph


# ── WorkflowState ─────────────────────────────────────────────────────────────

class WorkflowState(TypedDict):
    """State dict passed through every LangGraph node."""
    sot: dict[str, Any]          # ProjectState serialized via model_dump_jsonb()
    run_id: int
    pause_reason: str | None     # "waiting_user" | "waiting_approval" | None
    bot_response: str | None     # Next message to surface to the user
    approval_id: int | None      # DB id of a pending approval record


# ── Entry router ──────────────────────────────────────────────────────────────

def _route_entry(state: WorkflowState) -> str:
    """Map current_phase → the graph node to enter on (re-)invocation."""
    phase = state["sot"].get("current_phase", "init")
    return {
        "init":        "intake",
        "discovery":   "discovery",
        "market_eval": "market_eval_gate",  # re-enter at gate on resume
        "prd":         "prd_gate",          # re-enter at gate; skip re-generation
        "commercials": "commercials_gate",  # re-enter at gate on resume
        "sow":         "sow_gate",          # re-enter at gate; skip re-generation
        "completed":   "end",
    }.get(phase, "intake")


# ── Conditional edge routers ──────────────────────────────────────────────────

def _route_after_discovery(state: WorkflowState) -> str:
    return "pause" if state.get("pause_reason") else "continue"


def _route_after_market_eval_gate(state: WorkflowState) -> str:
    return "waiting" if state.get("pause_reason") else "approved"


def _route_after_prd_gate(state: WorkflowState) -> str:
    if state.get("pause_reason"):
        return "waiting"
    if state["sot"].get("rejection_feedback"):
        return "rejected"
    return "approved"


def _route_after_commercials_gate(state: WorkflowState) -> str:
    if state.get("pause_reason"):
        return "waiting"
    if state["sot"].get("rejection_feedback"):
        return "rejected"
    return "approved"


def _route_after_sow_gate(state: WorkflowState) -> str:
    if state.get("pause_reason"):
        return "waiting"
    if state["sot"].get("rejection_feedback"):
        return "rejected"
    return "approved"


# ── Graph builder ─────────────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    """Construct the LangGraph StateGraph (uncompiled)."""
    from app.workflow.nodes.intake import intake_normalize
    from app.workflow.nodes.discovery import discovery_loop
    from app.workflow.nodes.market_eval import market_eval_phase, market_eval_gate
    from app.workflow.nodes.prd import prd_phase
    from app.workflow.nodes.commercials import commercials_phase
    from app.workflow.nodes.approval_gate import (
        prd_approval_gate,
        commercials_approval_gate,
        sow_approval_gate,
    )
    from app.workflow.nodes.sow import sow_phase
    from app.workflow.nodes.end import end_node

    g = StateGraph(WorkflowState)

    # Register nodes
    g.add_node("intake",            intake_normalize)
    g.add_node("discovery",         discovery_loop)
    g.add_node("market_eval",       market_eval_phase)
    g.add_node("market_eval_gate",  market_eval_gate)
    g.add_node("prd",               prd_phase)
    g.add_node("prd_gate",          prd_approval_gate)
    g.add_node("commercials",       commercials_phase)
    g.add_node("commercials_gate",  commercials_approval_gate)
    g.add_node("sow",               sow_phase)
    g.add_node("sow_gate",          sow_approval_gate)
    g.add_node("end",               end_node)

    # Conditional entry — routes to correct node on start OR resume
    g.set_conditional_entry_point(
        _route_entry,
        {
            "intake":           "intake",
            "discovery":        "discovery",
            "market_eval_gate": "market_eval_gate",
            "prd_gate":         "prd_gate",
            "commercials_gate": "commercials_gate",
            "sow_gate":         "sow_gate",
            "end":              "end",
        },
    )

    # Fixed edges
    g.add_edge("intake",      "discovery")
    g.add_edge("market_eval", "market_eval_gate")
    g.add_edge("prd",         "prd_gate")
    g.add_edge("commercials", "commercials_gate")
    g.add_edge("sow",         "sow_gate")
    g.add_edge("end",         END)

    # Conditional edges — discovery
    g.add_conditional_edges(
        "discovery",
        _route_after_discovery,
        {"pause": END, "continue": "market_eval"},
    )

    # Conditional edges — market_eval gate
    g.add_conditional_edges(
        "market_eval_gate",
        _route_after_market_eval_gate,
        {"waiting": END, "approved": "prd"},
    )

    # Conditional edges — PRD gate (approval → commercials; rejection → re-run prd)
    g.add_conditional_edges(
        "prd_gate",
        _route_after_prd_gate,
        {"waiting": END, "rejected": "prd", "approved": "commercials"},
    )

    # Conditional edges — Commercials gate
    g.add_conditional_edges(
        "commercials_gate",
        _route_after_commercials_gate,
        {"waiting": END, "rejected": "commercials", "approved": "sow"},
    )

    # Conditional edges — SOW gate (rejection → re-run sow)
    g.add_conditional_edges(
        "sow_gate",
        _route_after_sow_gate,
        {"waiting": END, "rejected": "sow", "approved": "end"},
    )

    return g


@lru_cache(maxsize=1)
def get_workflow():
    """Compile and cache the workflow graph (lazy singleton)."""
    return build_graph().compile()
