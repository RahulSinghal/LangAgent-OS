"""ReadinessAgent — Phase 3.

Generates a deployment readiness checklist and collects cloud/infra preferences
after all coding milestones are approved.

Responsibilities:
  1. Read hosting_preference, scope, and sow_sections from SoT.
  2. LLM-generate a ReadinessCheckItem list covering infra, security, CI/CD,
     compliance, and handover categories.
  3. Populate deployment_prefs from the gathered_requirements (if available).
  4. Set approvals_status["readiness"] = pending so the readiness gate pauses.
  5. On re-run (rejection_feedback present): incorporate reviewer comments.
  6. Clear rejection_feedback after processing.
"""

from __future__ import annotations

from typing import Any

from app.agents.base import BaseAgent
from app.registry.loader import AgentLimits, AgentSpec
from app.sot.state import (
    ApprovalStatus,
    DeploymentPrefs,
    ProjectState,
    ReadinessCheckItem,
)


def _make_default_spec() -> AgentSpec:
    return AgentSpec(
        name="ReadinessAgent",
        role="deployment_engineer",
        description="Generates deployment readiness checklist and collects infra prefs",
        allowed_tools=[],
        limits=AgentLimits(max_steps=5, max_tool_calls=0, budget_usd=0.5),
    )


class ReadinessAgent(BaseAgent):
    """LLM-driven readiness agent that prepares the project for handover."""

    def __init__(self, spec: AgentSpec | None = None) -> None:
        super().__init__(spec or _make_default_spec())

    # ── BaseAgent interface ────────────────────────────────────────────────────

    def run(self, state: ProjectState) -> dict:
        """Generate checklist + deployment prefs, set readiness to pending."""
        from app.services.llm_service import call_llm_json  # lazy

        feedback_ctx = self._feedback_context(state)
        checklist = self._generate_checklist(state, call_llm_json, feedback_ctx)
        deployment_prefs = self._extract_deployment_prefs(state, call_llm_json)

        approvals = {k: v.value for k, v in state.approvals_status.items()}
        approvals["readiness"] = ApprovalStatus.PENDING.value

        return {
            "current_phase": "readiness",
            "readiness_checklist": [item.model_dump() for item in checklist],
            "deployment_prefs": deployment_prefs.model_dump(),
            "approvals_status": approvals,
            "rejection_feedback": None,  # consumed
        }

    # ── Private helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _feedback_context(state: ProjectState) -> str:
        fb = state.rejection_feedback
        if fb and fb.get("artifact_type") == "readiness":
            comment = fb.get("comment", "").strip()
            if comment:
                return f"\n\nREJECTION FEEDBACK TO ADDRESS:\n{comment}"
        return ""

    def _generate_checklist(
        self,
        state: ProjectState,
        call_llm_json,
        feedback_ctx: str,
    ) -> list[ReadinessCheckItem]:
        """LLM: generate a deployment readiness checklist."""
        past_ctx = self._past_context_block(state.past_context)
        hosting = state.hosting_preference or "client"
        system = (
            "You are a deployment engineer preparing a project for go-live. "
            f"Hosting model: {hosting}.\n\n"
            + past_ctx
            + "Generate a deployment readiness checklist as a JSON array.\n"
            "Each item:\n"
            '{"category": "infrastructure|security|cicd|compliance|handover", '
            '"item": "what must be confirmed or set up", '
            '"owner": "client|vendor"}\n\n'
            "Cover: cloud provisioning, DNS/SSL, secrets management, CI/CD pipeline, "
            "monitoring/alerting, data migration, compliance sign-off, "
            "runbook/knowledge transfer, and go-live communication plan.\n"
            "Return 10–20 items."
            + feedback_ctx
        )
        scope_text = str(state.scope or {})
        try:
            result = call_llm_json(system, f"Project scope:\n{scope_text}")
            items = result if isinstance(result, list) else result.get("checklist", [])
            return [
                ReadinessCheckItem(
                    category=i.get("category", "infrastructure"),
                    item=i.get("item", ""),
                    owner=i.get("owner", "client"),
                )
                for i in items
                if isinstance(i, dict) and i.get("item")
            ]
        except Exception:
            return _default_checklist(hosting)

    def _extract_deployment_prefs(
        self,
        state: ProjectState,
        call_llm_json,
    ) -> DeploymentPrefs:
        """LLM: infer cloud/infra preferences from gathered requirements."""
        gathered = state.gathered_requirements
        if not gathered:
            return state.deployment_prefs

        system = (
            "You are a cloud architect. "
            "Extract deployment preferences from the project requirements.\n\n"
            "Return JSON (use null for unknown values):\n"
            '{"cloud_provider": "aws|azure|gcp|on_prem|null", '
            '"region": "e.g. eu-west-1 or null", '
            '"compliance_requirements": ["GDPR", "SOC2", ...], '
            '"container_platform": "docker|kubernetes|ecs|null", '
            '"cicd_tool": "github_actions|gitlab_ci|jenkins|null", '
            '"monitoring_tool": "datadog|cloudwatch|grafana|null"}'
        )
        try:
            result = call_llm_json(system, f"Requirements:\n{gathered}")
            if isinstance(result, dict):
                return DeploymentPrefs(
                    cloud_provider=result.get("cloud_provider") or state.deployment_prefs.cloud_provider,
                    region=result.get("region") or state.deployment_prefs.region,
                    compliance_requirements=(
                        result.get("compliance_requirements")
                        or state.deployment_prefs.compliance_requirements
                    ),
                    container_platform=result.get("container_platform"),
                    cicd_tool=result.get("cicd_tool"),
                    monitoring_tool=result.get("monitoring_tool"),
                )
        except Exception:
            pass
        return state.deployment_prefs


def _default_checklist(hosting: str) -> list[ReadinessCheckItem]:
    """Minimal fallback checklist when LLM call fails."""
    owner = "client" if hosting in ("client", "client_server", "self_hosted") else "vendor"
    return [
        ReadinessCheckItem(category="infrastructure", item="Cloud environment provisioned", owner=owner),
        ReadinessCheckItem(category="security", item="SSL certificates configured", owner=owner),
        ReadinessCheckItem(category="cicd", item="CI/CD pipeline deployed and tested", owner="vendor"),
        ReadinessCheckItem(category="compliance", item="Data protection sign-off obtained", owner="client"),
        ReadinessCheckItem(category="handover", item="Runbook and knowledge transfer completed", owner="vendor"),
    ]
