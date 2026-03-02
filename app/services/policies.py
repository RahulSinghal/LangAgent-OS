"""Policy engine service — Phase 3C.

Evaluates governance policies for:
  - tool allowlists
  - budget constraints
  - approval thresholds
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models import Policy


# ── CRUD ──────────────────────────────────────────────────────────────────────

def create_policy(
    db: Session,
    org_id: int,
    name: str,
    policy_type: str,
    rules: dict,
    is_active: bool = True,
) -> Policy:
    """Create and persist a new governance policy."""
    policy = Policy(
        org_id=org_id,
        name=name,
        policy_type=policy_type,
        rules_jsonb=rules,
        is_active=is_active,
    )
    db.add(policy)
    db.commit()
    db.refresh(policy)
    return policy


def get_policy(db: Session, policy_id: int) -> Policy | None:
    """Return a policy by primary key, or None."""
    return db.query(Policy).filter(Policy.id == policy_id).first()


def list_policies(
    db: Session,
    org_id: int,
    active_only: bool = False,
) -> list[Policy]:
    """Return all policies for an org, optionally filtered to active ones."""
    q = db.query(Policy).filter(Policy.org_id == org_id)
    if active_only:
        q = q.filter(Policy.is_active == True)  # noqa: E712
    return q.order_by(Policy.id).all()


def update_policy(
    db: Session,
    policy_id: int,
    rules: dict | None = None,
    is_active: bool | None = None,
) -> Policy:
    """Update mutable fields on a policy.  Returns the updated policy."""
    policy = db.query(Policy).filter(Policy.id == policy_id).first()
    if policy is None:
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Policy {policy_id} not found",
        )
    if rules is not None:
        policy.rules_jsonb = rules
    if is_active is not None:
        policy.is_active = is_active
    policy.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(policy)
    return policy


def delete_policy(db: Session, policy_id: int) -> bool:
    """Delete a policy.  Returns True if deleted, False if not found."""
    policy = db.query(Policy).filter(Policy.id == policy_id).first()
    if policy is None:
        return False
    db.delete(policy)
    db.commit()
    return True


# ── Policy evaluation ─────────────────────────────────────────────────────────

def _evaluate_single(policy: Policy, context: dict) -> list[str]:
    """Evaluate one policy against *context*.  Returns list of violation strings."""
    violations: list[str] = []
    rules = policy.rules_jsonb or {}

    if policy.policy_type == "tool_allowlist":
        allowed_tools: list[str] = rules.get("allowed_tools", [])
        tool_name: str | None = context.get("tool_name")
        if allowed_tools and tool_name and tool_name not in allowed_tools:
            violations.append(
                f"Policy '{policy.name}': tool '{tool_name}' is not in the allowlist "
                f"{allowed_tools}"
            )

    elif policy.policy_type == "budget":
        max_cost: float = rules.get("max_cost_usd", float("inf"))
        actual_cost: float = context.get("cost_usd", 0)
        if actual_cost > max_cost:
            violations.append(
                f"Policy '{policy.name}': cost ${actual_cost:.4f} exceeds budget "
                f"limit ${max_cost:.4f}"
            )

    elif policy.policy_type == "approval_threshold":
        required_decisions: list[str] = rules.get("required_decisions", [])
        decision: str | None = context.get("decision")
        if required_decisions and decision and decision not in required_decisions:
            violations.append(
                f"Policy '{policy.name}': decision '{decision}' is not in required "
                f"set {required_decisions}"
            )

    return violations


def evaluate_policy(db: Session, org_id: int, context: dict) -> dict:
    """Evaluate all active policies for *org_id* against *context*.

    Returns::

        {
            "allowed": bool,
            "violations": list[str],
            "applied_policies": list[str],
        }
    """
    active_policies = list_policies(db, org_id=org_id, active_only=True)

    all_violations: list[str] = []
    applied: list[str] = []

    for policy in active_policies:
        violations = _evaluate_single(policy, context)
        applied.append(policy.name)
        all_violations.extend(violations)

    return {
        "allowed": len(all_violations) == 0,
        "violations": all_violations,
        "applied_policies": applied,
    }
