"""Integration tests for the policy engine — Phase 3C.

Tests: create_policy, get_policy, list_policies, update_policy,
       delete_policy, evaluate_policy (against live DB).
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.services.auth import create_org
from app.services.policies import (
    create_policy,
    delete_policy,
    evaluate_policy,
    get_policy,
    list_policies,
    update_policy,
)


# ── CRUD ──────────────────────────────────────────────────────────────────────

def test_create_policy_basic(db: Session):
    org = create_org(db, name="PolicyOrg Basic")
    policy = create_policy(
        db,
        org_id=org.id,
        name="Default Allowlist",
        policy_type="tool_allowlist",
        rules={"allowed_tools": ["web_search"]},
    )
    assert policy.id is not None
    assert policy.name == "Default Allowlist"
    assert policy.policy_type == "tool_allowlist"
    assert policy.is_active is True
    assert policy.org_id == org.id


def test_create_policy_stores_rules(db: Session):
    org = create_org(db, name="PolicyOrg Rules")
    rules = {"allowed_tools": ["a", "b", "c"]}
    policy = create_policy(db, org_id=org.id, name="RulesPolicy", policy_type="tool_allowlist", rules=rules)
    assert policy.rules_jsonb == rules


def test_create_policy_inactive(db: Session):
    org = create_org(db, name="PolicyOrg Inactive")
    policy = create_policy(
        db, org_id=org.id, name="InactivePolicy",
        policy_type="budget", rules={"max_cost_usd": 5.0}, is_active=False,
    )
    assert policy.is_active is False


def test_get_policy_found(db: Session):
    org = create_org(db, name="GetPolicy Org")
    policy = create_policy(db, org_id=org.id, name="GetMe", policy_type="budget", rules={})
    fetched = get_policy(db, policy.id)
    assert fetched is not None
    assert fetched.id == policy.id


def test_get_policy_not_found(db: Session):
    result = get_policy(db, policy_id=999999)
    assert result is None


def test_list_policies_by_org(db: Session):
    org = create_org(db, name="ListPolicy Org")
    create_policy(db, org_id=org.id, name="P1", policy_type="budget", rules={})
    create_policy(db, org_id=org.id, name="P2", policy_type="tool_allowlist", rules={})
    policies = list_policies(db, org_id=org.id)
    names = [p.name for p in policies]
    assert "P1" in names
    assert "P2" in names


def test_list_policies_active_only(db: Session):
    org = create_org(db, name="ActiveOnly Org")
    create_policy(db, org_id=org.id, name="Active", policy_type="budget", rules={}, is_active=True)
    create_policy(db, org_id=org.id, name="Inactive", policy_type="budget", rules={}, is_active=False)
    active = list_policies(db, org_id=org.id, active_only=True)
    names = [p.name for p in active]
    assert "Active" in names
    assert "Inactive" not in names


def test_list_policies_different_orgs_isolated(db: Session):
    org1 = create_org(db, name="IsolatedOrg1")
    org2 = create_org(db, name="IsolatedOrg2")
    create_policy(db, org_id=org1.id, name="Org1Policy", policy_type="budget", rules={})
    create_policy(db, org_id=org2.id, name="Org2Policy", policy_type="budget", rules={})
    org1_policies = list_policies(db, org_id=org1.id)
    names = [p.name for p in org1_policies]
    assert "Org1Policy" in names
    assert "Org2Policy" not in names


def test_update_policy_rules(db: Session):
    org = create_org(db, name="UpdatePolicy Org")
    policy = create_policy(
        db, org_id=org.id, name="UpdateMe",
        policy_type="tool_allowlist", rules={"allowed_tools": ["old_tool"]},
    )
    updated = update_policy(db, policy.id, rules={"allowed_tools": ["new_tool"]})
    assert updated.rules_jsonb == {"allowed_tools": ["new_tool"]}


def test_update_policy_is_active(db: Session):
    org = create_org(db, name="ToggleActive Org")
    policy = create_policy(db, org_id=org.id, name="Toggle", policy_type="budget", rules={}, is_active=True)
    updated = update_policy(db, policy.id, is_active=False)
    assert updated.is_active is False


def test_update_nonexistent_policy_raises(db: Session):
    with pytest.raises(HTTPException) as exc_info:
        update_policy(db, policy_id=999999, rules={})
    assert exc_info.value.status_code == 404


def test_delete_policy(db: Session):
    org = create_org(db, name="DeletePolicy Org")
    policy = create_policy(db, org_id=org.id, name="DeleteMe", policy_type="budget", rules={})
    result = delete_policy(db, policy.id)
    assert result is True
    assert get_policy(db, policy.id) is None


def test_delete_nonexistent_policy_returns_false(db: Session):
    result = delete_policy(db, policy_id=999999)
    assert result is False


# ── Policy evaluation against DB ──────────────────────────────────────────────

def test_evaluate_no_policies_allows(db: Session):
    org = create_org(db, name="EvalNoPolicy Org")
    result = evaluate_policy(db, org_id=org.id, context={"tool_name": "anything"})
    assert result["allowed"] is True


def test_evaluate_tool_allowlist_pass(db: Session):
    org = create_org(db, name="EvalAllow Org")
    create_policy(
        db, org_id=org.id, name="Allowlist",
        policy_type="tool_allowlist", rules={"allowed_tools": ["web_search"]},
    )
    result = evaluate_policy(db, org_id=org.id, context={"tool_name": "web_search"})
    assert result["allowed"] is True
    assert "Allowlist" in result["applied_policies"]


def test_evaluate_tool_allowlist_violation(db: Session):
    org = create_org(db, name="EvalBlock Org")
    create_policy(
        db, org_id=org.id, name="StrictAllowlist",
        policy_type="tool_allowlist", rules={"allowed_tools": ["web_search"]},
    )
    result = evaluate_policy(db, org_id=org.id, context={"tool_name": "exec_code"})
    assert result["allowed"] is False
    assert len(result["violations"]) > 0


def test_evaluate_budget_pass(db: Session):
    org = create_org(db, name="EvalBudget Org")
    create_policy(
        db, org_id=org.id, name="BudgetCap",
        policy_type="budget", rules={"max_cost_usd": 50.0},
    )
    result = evaluate_policy(db, org_id=org.id, context={"cost_usd": 10.0})
    assert result["allowed"] is True


def test_evaluate_budget_violation(db: Session):
    org = create_org(db, name="EvalBudgetViolation Org")
    create_policy(
        db, org_id=org.id, name="TightBudget",
        policy_type="budget", rules={"max_cost_usd": 1.0},
    )
    result = evaluate_policy(db, org_id=org.id, context={"cost_usd": 50.0})
    assert result["allowed"] is False


def test_evaluate_inactive_policies_skipped(db: Session):
    org = create_org(db, name="EvalInactive Org")
    create_policy(
        db, org_id=org.id, name="InactiveBlock",
        policy_type="tool_allowlist",
        rules={"allowed_tools": ["safe_only"]},
        is_active=False,
    )
    result = evaluate_policy(db, org_id=org.id, context={"tool_name": "unsafe_tool"})
    # Inactive policy should not fire
    assert result["allowed"] is True
