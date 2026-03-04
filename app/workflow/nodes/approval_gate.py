"""Approval gate nodes — Phase 4 (extends Phase 1E / 1F).

Each gate checks the SoT's approvals_status for the relevant artifact.

  approved  → continue to next phase
  pending   → pause (waiting_approval); run engine creates Approval record
  rejected  → load rejection comment from DB, patch rejection_feedback into SoT,
               re-route back to the generating agent (no pause)

Phase 4 adds:
  - REJECTED handling with rejection_feedback → re-generation loop
  - commercials_approval_gate
"""

from __future__ import annotations

from app.sot.patch import apply_patch
from app.sot.state import ApprovalStatus, ProjectState


def _load_rejection_comment(run_id: int | None, approval_type: str) -> str:
    """Load latest rejection comments for a run+type (if any)."""
    if run_id is None:
        return ""
    try:
        from app.db.session import SessionLocal
        from app.db.models import Approval
        with SessionLocal() as db:
            record = (
                db.query(Approval)
                .filter(
                    Approval.run_id == run_id,
                    Approval.type == approval_type,
                    Approval.status == "rejected",
                )
                .order_by(Approval.requested_at.desc())
                .first()
            )
            return record.comments if (record and record.comments) else ""
    except Exception:
        return ""


def _gate(state: dict, artifact_type: str) -> dict:
    """Generic approval gate logic shared by most gates."""
    sot = ProjectState(**state["sot"])
    status = sot.approvals_status.get(artifact_type)

    # ── Approved ──────────────────────────────────────────────────────────────
    if status == ApprovalStatus.APPROVED:
        return {
            "sot": state["sot"],
            "pause_reason": None,
            "bot_response": None,
        }

    # ── Rejected — load comment, patch rejection_feedback, route back ─────────
    if status == ApprovalStatus.REJECTED:
        comment = _load_rejection_comment(state.get("run_id"), artifact_type)

        # Reset approval to pending so the gate will pause again after re-generation
        current = {k: v.value for k, v in sot.approvals_status.items()}
        current[artifact_type] = ApprovalStatus.PENDING.value

        # Remove the artifact index entry so the next pause triggers a new version render
        idx = {k: v.model_dump() for k, v in sot.artifacts_index.items()}
        idx.pop(artifact_type, None)

        updated_sot = apply_patch(sot, {
            "approvals_status": current,
            "artifacts_index": idx,
            "rejection_feedback": {
                "artifact_type": artifact_type,
                "comment": comment,
            },
        })
        return {
            "sot": updated_sot.model_dump_jsonb(),
            "pause_reason": None,  # do NOT pause — loop back to agent node
            "bot_response": (
                f"{artifact_type.upper()} was rejected. "
                "Regenerating with reviewer feedback…"
            ),
        }

    # ── Pending (or not yet set) — pause and wait for review ──────────────────
    current = {k: v.value for k, v in sot.approvals_status.items()}
    if current.get(artifact_type) != ApprovalStatus.PENDING.value:
        current[artifact_type] = ApprovalStatus.PENDING.value
        sot = apply_patch(sot, {"approvals_status": current})

    return {
        "sot": sot.model_dump_jsonb(),
        "pause_reason": "waiting_approval",
        "bot_response": (
            f"{artifact_type.upper()} approval required. "
            "Please review the artifact and POST to /approvals/{id}/resolve."
        ),
    }


def prd_approval_gate(state: dict) -> dict:
    """Gate that pauses until PRD AND required server-details approval are approved."""
    sot = ProjectState(**state["sot"])
    hp = (sot.hosting_preference or "client").lower().strip()
    required: list[str] = ["prd"]
    if hp in ("client", "client_server", "client-hosted", "self_hosted", "self-hosted", "own_server"):
        required.append("server_details_client")
    else:
        required.append("server_details_infra")

    # If any required is rejected, handle the first rejected (route back)
    for t in required:
        if sot.approvals_status.get(t) == ApprovalStatus.REJECTED:
            return _gate({**state, "sot": state["sot"]}, t)

    # If all required approved → continue
    if all(sot.approvals_status.get(t) == ApprovalStatus.APPROVED for t in required):
        return {"sot": state["sot"], "pause_reason": None, "bot_response": None}

    # Otherwise ensure required are pending and pause
    approvals = {k: v.value for k, v in sot.approvals_status.items()}
    changed = False
    for t in required:
        if approvals.get(t) != ApprovalStatus.PENDING.value:
            approvals[t] = ApprovalStatus.PENDING.value
            changed = True
    if changed:
        sot = apply_patch(sot, {"approvals_status": approvals})

    return {
        "sot": sot.model_dump_jsonb(),
        "pause_reason": "waiting_approval",
        "bot_response": "PRD + hosting/server details approval required.",
    }


def commercials_approval_gate(state: dict) -> dict:
    """Gate that pauses until the commercial proposal is approved."""
    return _gate(state, "commercials")


def sow_approval_gate(state: dict) -> dict:
    """Gate that pauses until the SOW is approved (or re-routes on rejection)."""
    return _gate(state, "sow")


def coding_plan_approval_gate(state: dict) -> dict:
    """Gate that pauses until the tech lead approves the coding milestone plan."""
    return _gate(state, "coding_plan")


def milestone_approval_gate(state: dict) -> dict:
    """Per-milestone tech lead review gate.

    On approval:
      - Marks the current milestone as "approved" in coding_plan.
      - If more milestones remain: advances current_milestone_index so
        coding_milestone_phase picks up the next one (loop continues).
      - If all milestones done: passes through to end node.
    On rejection:
      - Loads reviewer comment from DB.
      - Resets the per-milestone approval to pending.
      - Patches rejection_feedback so MilestoneCodeAgent incorporates it.
      - Does NOT pause — the conditional edge loops back to coding_milestone_phase.
    """
    sot = ProjectState(**state["sot"])
    idx = sot.current_milestone_index
    plan = sot.coding_plan

    if not plan or idx >= len(plan):
        # Guard: nothing in plan or index out of range — pass through.
        return {"sot": state["sot"], "pause_reason": None, "bot_response": None}

    milestone = plan[idx]
    approval_key = f"milestone_{milestone.id}"
    status = sot.approvals_status.get(approval_key)

    # ── Approved ──────────────────────────────────────────────────────────────
    if status == ApprovalStatus.APPROVED:
        updated_plan = [m.model_dump() for m in plan]
        updated_plan[idx]["status"] = "approved"

        if idx + 1 < len(plan):
            # More milestones — advance index and loop back.
            new_sot = apply_patch(sot, {
                "coding_plan": updated_plan,
                "current_milestone_index": idx + 1,
            })
            return {
                "sot": new_sot.model_dump_jsonb(),
                "pause_reason": None,
                "bot_response": (
                    f"Milestone '{milestone.name}' approved. "
                    f"Starting milestone {idx + 2} of {len(plan)}…"
                ),
            }
        else:
            # All milestones approved — fall through to end.
            new_sot = apply_patch(sot, {"coding_plan": updated_plan})
            return {
                "sot": new_sot.model_dump_jsonb(),
                "pause_reason": None,
                "bot_response": "All milestones approved. Proceeding to next phase.",
            }

    # ── Rejected — load comment, patch rejection_feedback, route back ─────────
    if status == ApprovalStatus.REJECTED:
        comment = _load_rejection_comment(state.get("run_id"), approval_key)

        updated_plan = [m.model_dump() for m in plan]
        updated_plan[idx]["status"] = "rejected"

        current_approvals = {k: v.value for k, v in sot.approvals_status.items()}
        current_approvals[approval_key] = ApprovalStatus.PENDING.value

        new_sot = apply_patch(sot, {
            "coding_plan": updated_plan,
            "approvals_status": current_approvals,
            "rejection_feedback": {
                "artifact_type": approval_key,
                "comment": comment,
            },
        })
        return {
            "sot": new_sot.model_dump_jsonb(),
            "pause_reason": None,
            "bot_response": (
                f"Milestone '{milestone.name}' rejected. "
                "Regenerating with reviewer feedback…"
            ),
        }

    # ── Pending (or not yet set) — pause and wait for tech lead ──────────────
    current_approvals = {k: v.value for k, v in sot.approvals_status.items()}
    if current_approvals.get(approval_key) != ApprovalStatus.PENDING.value:
        current_approvals[approval_key] = ApprovalStatus.PENDING.value
        sot = apply_patch(sot, {"approvals_status": current_approvals})

    return {
        "sot": sot.model_dump_jsonb(),
        "pause_reason": "waiting_approval",
        "bot_response": (
            f"Milestone '{milestone.name}' ({idx + 1}/{len(plan)}) is ready for "
            "tech lead review. POST to /approvals/{id}/resolve to continue."
        ),
    }
