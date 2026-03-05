"""LangGraph workflow graph — Phase 4 (Phase 3 readiness added).

Graph structure:

  [conditional_entry_point] ─── routes to right node based on current_phase
        │
        ├─ intake  →  discovery  →  [pause→END | continue→market_eval
        │                              | fast_market_eval→market_eval_gate
        │                              | fast_prd→prd_gate | fast_commercials→commercials_gate
        │                              | fast_sow→sow_gate | fast_coding→coding_plan]
        │                    ↑ fast_* fires when the user provided that phase's input doc
        │
        ├─ market_eval → market_eval_gate → [waiting→END | approved→prd]
        │
        ├─ prd    →  prd_gate       → [waiting→END | rejected→prd | approved→commercials]
        │
        ├─ commercials → commercials_gate → [waiting→END | rejected→commercials | approved→sow]
        │
        ├─ sow    →  sow_gate       → [waiting→END | rejected→sow | approved→user_guide]
        │
        ├─ user_guide  → [waiting→END | continue→coding_plan]
        │                  (asks user if they want a user guide; generates on yes)
        │
        ├─ coding_plan → coding_plan_gate → [waiting→END | rejected→coding_plan
        │                                     | approved→coding_milestone]
        │
        ├─ coding_milestone → milestone_gate → [waiting→END | rejected→coding_milestone
        │                                        | next_milestone→coding_milestone
        │                                        | all_done→readiness]
        │
        ├─ readiness → readiness_gate → [waiting→END | rejected→readiness | approved→end]
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
        "market_eval": "market_eval_gate",   # re-enter at gate on resume
        "prd":         "prd_gate",           # re-enter at gate; skip re-generation
        "commercials": "commercials_gate",   # re-enter at gate on resume
        "sow":         "sow_gate",           # re-enter at gate; skip re-generation
        "user_guide":  "user_guide",         # re-enter at user guide node on resume
        "coding":      "coding_plan_gate",   # re-enter at plan gate on resume
        "milestone":   "milestone_gate",     # re-enter at milestone gate on resume
        "readiness":   "readiness_gate",     # re-enter at readiness gate on resume
        "completed":   "end",
    }.get(phase, "intake")


# ── Conditional edge routers ──────────────────────────────────────────────────

# Maps document_type → conditional-edge key → graph node (see build_graph edges).
# Each document type represents the "input" for a specific phase.  When
# discovery completes after validating that input (gap Q&A), the graph fast-
# tracks directly to the appropriate gate or generator node.
_DOC_TYPE_ROUTE: dict[str, str] = {
    "market_eval":      "fast_market_eval",   # → market_eval_gate
    "prd":              "fast_prd",            # → prd_gate  (uploaded doc IS the PRD)
    "commercials":      "fast_commercials",    # → commercials_gate
    "sow":              "fast_sow",            # → sow_gate  (uploaded doc IS the SOW)
    "technical_design": "fast_coding",         # → coding_plan (need to generate plan)
    # "brd" and "unknown" → normal "continue" → market_eval
}


def _route_after_discovery(state: WorkflowState) -> str:
    if state.get("pause_reason"):
        return "pause"
    doc_type = state["sot"].get("document_type") or ""
    return _DOC_TYPE_ROUTE.get(doc_type, "continue")


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


def _route_after_user_guide(state: WorkflowState) -> str:
    """Pause if waiting for user reply; otherwise always continue to coding_plan."""
    if state.get("pause_reason"):
        return "waiting"
    return "continue"


def _route_after_coding_plan_gate(state: WorkflowState) -> str:
    if state.get("pause_reason"):
        return "waiting"
    if state["sot"].get("rejection_feedback"):
        return "rejected"
    return "approved"


def _route_after_milestone_gate(state: WorkflowState) -> str:
    if state.get("pause_reason"):
        return "waiting"
    if state["sot"].get("rejection_feedback"):
        return "rejected"
    # Approved: check if more milestones remain (gate node already advanced index).
    sot = state["sot"]
    idx = sot.get("current_milestone_index", 0)
    plan = sot.get("coding_plan", [])
    if idx < len(plan):
        return "next_milestone"
    return "all_done"  # → readiness phase


def _route_after_readiness_gate(state: WorkflowState) -> str:
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
        coding_plan_approval_gate,
        milestone_approval_gate,
        readiness_approval_gate,
    )
    from app.workflow.nodes.sow import sow_phase
    from app.workflow.nodes.user_guide import user_guide_phase
    from app.workflow.nodes.coding_plan import coding_plan_phase
    from app.workflow.nodes.coding_milestone import coding_milestone_phase
    from app.workflow.nodes.readiness import readiness_phase
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
    g.add_node("user_guide",        user_guide_phase)
    g.add_node("coding_plan",       coding_plan_phase)
    g.add_node("coding_plan_gate",  coding_plan_approval_gate)
    g.add_node("coding_milestone",  coding_milestone_phase)
    g.add_node("milestone_gate",    milestone_approval_gate)
    g.add_node("readiness",         readiness_phase)
    g.add_node("readiness_gate",    readiness_approval_gate)
    g.add_node("end",               end_node)

    # Conditional entry — routes to correct node on start OR resume
    g.set_conditional_entry_point(
        _route_entry,
        {
            "intake":            "intake",
            "discovery":         "discovery",
            "market_eval_gate":  "market_eval_gate",
            "prd_gate":          "prd_gate",
            "commercials_gate":  "commercials_gate",
            "sow_gate":          "sow_gate",
            "user_guide":        "user_guide",
            "coding_plan_gate":  "coding_plan_gate",
            "milestone_gate":    "milestone_gate",
            "readiness_gate":    "readiness_gate",
            "end":               "end",
        },
    )

    # Fixed edges
    g.add_edge("intake",           "discovery")
    g.add_edge("market_eval",      "market_eval_gate")
    g.add_edge("prd",              "prd_gate")
    g.add_edge("commercials",      "commercials_gate")
    g.add_edge("sow",              "sow_gate")
    g.add_edge("coding_plan",      "coding_plan_gate")
    g.add_edge("coding_milestone", "milestone_gate")
    g.add_edge("readiness",        "readiness_gate")
    g.add_edge("end",              END)

    # Conditional edges — discovery
    # Each fast_* key skips intermediate phases when the user has already provided
    # that phase's input document (validated by gap Q&A in discovery first).
    g.add_conditional_edges(
        "discovery",
        _route_after_discovery,
        {
            "pause":            END,
            "continue":         "market_eval",
            "fast_market_eval": "market_eval_gate",   # skip market_eval generation
            "fast_prd":         "prd_gate",            # skip market_eval + PRD gen
            "fast_commercials": "commercials_gate",    # skip up to commercials gate
            "fast_sow":         "sow_gate",            # skip to SOW gate
            "fast_coding":      "coding_plan",         # skip to coding plan generator
        },
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

    # Conditional edges — SOW gate → user_guide (ask if guide wanted) → coding_plan
    g.add_conditional_edges(
        "sow_gate",
        _route_after_sow_gate,
        {"waiting": END, "rejected": "sow", "approved": "user_guide"},
    )

    # Conditional edges — user_guide (pause if waiting; continue → coding_plan)
    g.add_conditional_edges(
        "user_guide",
        _route_after_user_guide,
        {"waiting": END, "continue": "coding_plan"},
    )

    # Conditional edges — coding plan gate
    g.add_conditional_edges(
        "coding_plan_gate",
        _route_after_coding_plan_gate,
        {"waiting": END, "rejected": "coding_plan", "approved": "coding_milestone"},
    )

    # Conditional edges — milestone gate (loop or finish → readiness)
    g.add_conditional_edges(
        "milestone_gate",
        _route_after_milestone_gate,
        {
            "waiting":        END,
            "rejected":       "coding_milestone",  # redo current milestone
            "next_milestone": "coding_milestone",  # advance index, loop back
            "all_done":       "readiness",         # all milestones approved → deploy readiness
        },
    )

    # Conditional edges — readiness gate
    g.add_conditional_edges(
        "readiness_gate",
        _route_after_readiness_gate,
        {"waiting": END, "rejected": "readiness", "approved": "end"},
    )

    return g


@lru_cache(maxsize=1)
def get_workflow():
    """Compile and cache the workflow graph (lazy singleton)."""
    return build_graph().compile()
