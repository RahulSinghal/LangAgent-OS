"""Scaffold node — Step 4 (post-code).

Runs ScaffoldAgent after all milestones are approved.
Generates Dockerfile, docker-compose.yml, .env.example,
CI/CD workflows, README, and dependency files.
"""

from __future__ import annotations

from app.agents.scaffold_agent import ScaffoldAgent
from app.sot.state import ProjectState


def scaffold_phase(state: dict) -> dict:
    """Execute ScaffoldAgent and write scaffolding files to disk.

    Args:
        state: WorkflowState dict.

    Returns:
        Partial WorkflowState update with updated SoT.
    """
    sot = ProjectState(**state["sot"])
    agent = ScaffoldAgent()
    new_sot = agent.execute(sot)
    return {
        "sot": new_sot.model_dump_jsonb(),
        "pause_reason": None,
        "bot_response": None,
    }
