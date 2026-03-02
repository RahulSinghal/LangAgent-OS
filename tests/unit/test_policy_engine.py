"""Unit tests for the policy evaluation logic — Phase 3C.

Tests _evaluate_single rules (tool_allowlist, budget, approval_threshold)
by calling evaluate_policy with a mocked DB session.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.policies import (
    _evaluate_single,
    evaluate_policy,
)
from app.db.models import Policy


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_policy(policy_type: str, rules: dict, name: str = "TestPolicy") -> Policy:
    p = Policy()
    p.id = 1
    p.name = name
    p.policy_type = policy_type
    p.rules_jsonb = rules
    p.is_active = True
    return p


# ── tool_allowlist ────────────────────────────────────────────────────────────

def test_tool_allowlist_allowed_tool():
    policy = _make_policy("tool_allowlist", {"allowed_tools": ["web_search", "fetch_url"]})
    violations = _evaluate_single(policy, {"tool_name": "web_search"})
    assert violations == []


def test_tool_allowlist_blocked_tool():
    policy = _make_policy("tool_allowlist", {"allowed_tools": ["web_search"]})
    violations = _evaluate_single(policy, {"tool_name": "exec_code"})
    assert len(violations) == 1
    assert "exec_code" in violations[0]


def test_tool_allowlist_empty_list_allows_any():
    policy = _make_policy("tool_allowlist", {"allowed_tools": []})
    violations = _evaluate_single(policy, {"tool_name": "anything"})
    assert violations == []


def test_tool_allowlist_no_tool_in_context_no_violation():
    policy = _make_policy("tool_allowlist", {"allowed_tools": ["web_search"]})
    violations = _evaluate_single(policy, {})
    assert violations == []


def test_tool_allowlist_multiple_allowed_tools():
    policy = _make_policy(
        "tool_allowlist",
        {"allowed_tools": ["web_search", "fetch_url", "file_read"]},
    )
    for tool in ["web_search", "fetch_url", "file_read"]:
        violations = _evaluate_single(policy, {"tool_name": tool})
        assert violations == [], f"Expected no violation for {tool}"


# ── budget ────────────────────────────────────────────────────────────────────

def test_budget_within_limit():
    policy = _make_policy("budget", {"max_cost_usd": 10.0})
    violations = _evaluate_single(policy, {"cost_usd": 5.0})
    assert violations == []


def test_budget_exactly_at_limit():
    policy = _make_policy("budget", {"max_cost_usd": 10.0})
    violations = _evaluate_single(policy, {"cost_usd": 10.0})
    assert violations == []


def test_budget_exceeded():
    policy = _make_policy("budget", {"max_cost_usd": 10.0})
    violations = _evaluate_single(policy, {"cost_usd": 10.01})
    assert len(violations) == 1
    assert "budget" in violations[0].lower() or "limit" in violations[0].lower()


def test_budget_zero_cost_no_violation():
    policy = _make_policy("budget", {"max_cost_usd": 0.0})
    violations = _evaluate_single(policy, {"cost_usd": 0.0})
    assert violations == []


def test_budget_no_limit_allows_any_cost():
    policy = _make_policy("budget", {})  # no max_cost_usd → defaults to inf
    violations = _evaluate_single(policy, {"cost_usd": 99999.0})
    assert violations == []


# ── approval_threshold ────────────────────────────────────────────────────────

def test_approval_threshold_valid_decision():
    policy = _make_policy(
        "approval_threshold",
        {"required_decisions": ["approved", "conditionally_approved"]},
    )
    violations = _evaluate_single(policy, {"decision": "approved"})
    assert violations == []


def test_approval_threshold_invalid_decision():
    policy = _make_policy(
        "approval_threshold",
        {"required_decisions": ["approved"]},
    )
    violations = _evaluate_single(policy, {"decision": "rejected"})
    assert len(violations) == 1
    assert "rejected" in violations[0]


def test_approval_threshold_no_decision_in_context():
    policy = _make_policy(
        "approval_threshold",
        {"required_decisions": ["approved"]},
    )
    violations = _evaluate_single(policy, {})
    assert violations == []


def test_approval_threshold_empty_required_list_allows_any():
    policy = _make_policy("approval_threshold", {"required_decisions": []})
    violations = _evaluate_single(policy, {"decision": "anything"})
    assert violations == []


# ── evaluate_policy (via mocked DB) ──────────────────────────────────────────

def _mock_db_with_policies(policies: list[Policy]):
    db = MagicMock()
    # Mock list_policies to return the given policies
    return db, policies


def test_evaluate_policy_no_policies_allows_all():
    with patch("app.services.policies.list_policies", return_value=[]):
        db = MagicMock()
        result = evaluate_policy(db, org_id=1, context={"tool_name": "anything"})
    assert result["allowed"] is True
    assert result["violations"] == []
    assert result["applied_policies"] == []


def test_evaluate_policy_single_violation():
    policy = _make_policy("tool_allowlist", {"allowed_tools": ["safe_tool"]}, name="AllowList")
    with patch("app.services.policies.list_policies", return_value=[policy]):
        db = MagicMock()
        result = evaluate_policy(db, org_id=1, context={"tool_name": "unsafe_tool"})
    assert result["allowed"] is False
    assert len(result["violations"]) == 1
    assert "AllowList" in result["applied_policies"]


def test_evaluate_policy_all_pass():
    p1 = _make_policy("tool_allowlist", {"allowed_tools": ["web_search"]}, name="P1")
    p2 = _make_policy("budget", {"max_cost_usd": 100.0}, name="P2")
    with patch("app.services.policies.list_policies", return_value=[p1, p2]):
        db = MagicMock()
        result = evaluate_policy(
            db, org_id=1,
            context={"tool_name": "web_search", "cost_usd": 5.0},
        )
    assert result["allowed"] is True
    assert result["applied_policies"] == ["P1", "P2"]


def test_evaluate_policy_multiple_violations():
    p1 = _make_policy("tool_allowlist", {"allowed_tools": ["safe"]}, name="Allowlist")
    p2 = _make_policy("budget", {"max_cost_usd": 1.0}, name="BudgetCap")
    with patch("app.services.policies.list_policies", return_value=[p1, p2]):
        db = MagicMock()
        result = evaluate_policy(
            db, org_id=1,
            context={"tool_name": "unsafe", "cost_usd": 50.0},
        )
    assert result["allowed"] is False
    assert len(result["violations"]) == 2
