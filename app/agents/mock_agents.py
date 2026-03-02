"""Deterministic mock agents — Phase 1D.

No external LLM required. Each mock returns a hardcoded patch so CI passes
without API keys. Used by integration and contract tests.

Mocks:
  MockDiscoveryAgent — appends a fixed open_question
  MockPRDAgent       — transitions phase to PRD, sets approval to pending
  MockSOWAgent       — transitions phase to SOW, sets approval to pending
"""

from __future__ import annotations

import re

from app.agents.base import BaseAgent
from app.registry.loader import AgentSpec, AgentLimits
from app.sot.state import ApprovalStatus, ProjectState, QuestionItem, RequirementItem


# ── Shared spec factory ───────────────────────────────────────────────────────

def _mock_spec(name: str, role: str, allowed_tools: list[str] | None = None) -> AgentSpec:
    return AgentSpec(
        name=name,
        role=role,
        description=f"Mock {name} for testing",
        allowed_tools=allowed_tools or [],
        limits=AgentLimits(max_steps=5, max_tool_calls=2, budget_usd=0.0),
    )


# ── Mock agents ───────────────────────────────────────────────────────────────

class MockDiscoveryAgent(BaseAgent):
    """Returns a fixed patch: appends one open_question and one requirement."""

    def __init__(self) -> None:
        super().__init__(_mock_spec("MockDiscoveryAgent", "analyst"))

    def run(self, state: ProjectState) -> dict:
        existing_questions = [q.model_dump() for q in state.open_questions]
        existing_reqs = [r.model_dump() for r in state.requirements]

        msg = (state.last_user_message or "").strip()
        msg_norm = re.sub(r"[^a-z0-9\\s]+", " ", msg.lower()).strip()
        words = [w for w in msg_norm.split() if w]

        # Deterministic hosting preference heuristic
        hosting_pref = "vendor" if "our server" in msg_norm else "client"
        new_req = RequirementItem(
            category="functional",
            text="User can authenticate via SSO",
            source="discovery",
        ).model_dump()

        # Deterministic behavior for tests:
        # - First call: always pauses by creating a question (even if message is meaningful).
        # - Second call: if user answered (last_user_message present) and it's not a pure greeting,
        #   complete discovery so the workflow can advance deterministically.
        is_greeting_only = bool(
            re.fullmatch(
                r"(hi|hello|hey|thanks|thx|ok|okay|good\\s+(morning|afternoon|evening))",
                msg_norm,
            )
        )

        # Second call heuristic: if a prior question exists, treat the incoming
        # message as an answer and complete discovery.
        if msg and existing_questions and not is_greeting_only:
            return {
                "current_phase": "discovery",
                "hosting_preference": hosting_pref,
                "requirements": [*existing_reqs, new_req],
                "discovery_complete": True,
                "last_user_message": None,
            }

        new_question = QuestionItem(
            question="What is the primary use case?",
            category="scope",
        ).model_dump()
        return {
            "current_phase": "discovery",
            "hosting_preference": hosting_pref,
            "open_questions": [*existing_questions, new_question],
            "requirements": [*existing_reqs, new_req],
            "discovery_complete": False,
            "last_user_message": None,  # consume greeting/short message
        }


class MockPRDAgent(BaseAgent):
    """Returns a patch that transitions the run to PRD phase and raises the approval gate."""

    def __init__(self) -> None:
        super().__init__(_mock_spec("MockPRDAgent", "product_manager"))

    def run(self, state: ProjectState) -> dict:
        approvals = {k: v.value for k, v in state.approvals_status.items()}
        approvals["prd"] = ApprovalStatus.PENDING.value
        hp = (state.hosting_preference or "client").lower().strip()
        if hp == "client":
            approvals["server_details_client"] = ApprovalStatus.PENDING.value
            approvals.pop("server_details_infra", None)
        else:
            approvals["server_details_infra"] = ApprovalStatus.PENDING.value
            approvals.pop("server_details_client", None)
        return {
            "current_phase": "prd",
            "approvals_status": approvals,
        }


class MockSOWAgent(BaseAgent):
    """Returns a patch that transitions the run to SOW phase and raises the approval gate."""

    def __init__(self) -> None:
        super().__init__(_mock_spec("MockSOWAgent", "engagement_manager"))

    def run(self, state: ProjectState) -> dict:
        approvals = {k: v.value for k, v in state.approvals_status.items()}
        approvals["sow"] = ApprovalStatus.PENDING.value
        return {
            "current_phase": "sow",
            "approvals_status": approvals,
        }
