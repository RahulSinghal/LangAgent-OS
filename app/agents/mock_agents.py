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
from app.sot.state import ApprovalStatus, MilestoneItem, ProjectState, QuestionItem, RequirementItem


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


class MockCodingPlanAgent(BaseAgent):
    """Returns a deterministic 2-milestone coding plan for testing."""

    def __init__(self) -> None:
        super().__init__(_mock_spec("MockCodingPlanAgent", "tech_lead"))

    def run(self, state: ProjectState) -> dict:
        approvals = {k: v.value for k, v in state.approvals_status.items()}
        approvals["coding_plan"] = ApprovalStatus.PENDING.value
        return {
            "current_phase": "coding",
            "coding_plan": [
                MilestoneItem(
                    name="Foundation & Auth",
                    description="Core infrastructure, database models, and authentication.",
                    stories=["story-001", "story-002"],
                    expected_evals=[
                        "unit: user model validation",
                        "unit: password hashing",
                        "integration: auth token lifecycle",
                        "e2e: login flow",
                    ],
                ).model_dump(),
                MilestoneItem(
                    name="Feature Implementation",
                    description="Primary feature set as defined in PRD requirements.",
                    stories=["story-003", "story-004"],
                    expected_evals=[
                        "unit: feature business logic",
                        "integration: API endpoints",
                        "e2e: end-to-end user journey",
                    ],
                ).model_dump(),
            ],
            "current_milestone_index": 0,
            "approvals_status": approvals,
            "rejection_feedback": None,
        }


class MockMilestoneCodeAgent(BaseAgent):
    """Returns a stub patch for the current milestone — no actual files written."""

    def __init__(self) -> None:
        super().__init__(_mock_spec("MockMilestoneCodeAgent", "engineer"))

    def run(self, state: ProjectState) -> dict:
        idx = state.current_milestone_index
        plan = state.coding_plan
        if not plan or idx >= len(plan):
            return {}
        milestone = plan[idx]
        approval_key = f"milestone_{milestone.id}"
        approvals = {k: v.value for k, v in state.approvals_status.items()}
        approvals[approval_key] = ApprovalStatus.PENDING.value
        updated_plan = [m.model_dump() for m in plan]
        updated_plan[idx]["status"] = "in_progress"
        return {
            "current_phase": "milestone",
            "coding_plan": updated_plan,
            "approvals_status": approvals,
            "rejection_feedback": None,
        }
