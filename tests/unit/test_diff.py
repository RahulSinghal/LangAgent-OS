"""Unit tests for SoT diff utilities — Phase 3D.

Tests: diff_states, diff_summary, detect_changes.
"""

from __future__ import annotations

import pytest

from app.sot.diff import detect_changes, diff_states, diff_summary


# ── diff_states ───────────────────────────────────────────────────────────────

def test_diff_states_identical_returns_empty():
    old = {"a": 1, "b": "hello"}
    new = {"a": 1, "b": "hello"}
    assert diff_states(old, new) == []


def test_diff_states_changed_scalar():
    old = {"title": "Old Title"}
    new = {"title": "New Title"}
    changes = diff_states(old, new)
    assert len(changes) == 1
    assert changes[0]["op"] == "changed"
    assert changes[0]["path"] == "title"
    assert changes[0]["old"] == "Old Title"
    assert changes[0]["new"] == "New Title"


def test_diff_states_added_key():
    old = {"a": 1}
    new = {"a": 1, "b": 2}
    changes = diff_states(old, new)
    assert len(changes) == 1
    assert changes[0]["op"] == "added"
    assert changes[0]["path"] == "b"
    assert changes[0]["new"] == 2


def test_diff_states_removed_key():
    old = {"a": 1, "b": 2}
    new = {"a": 1}
    changes = diff_states(old, new)
    assert len(changes) == 1
    assert changes[0]["op"] == "removed"
    assert changes[0]["path"] == "b"
    assert changes[0]["old"] == 2


def test_diff_states_nested_dict():
    old = {"meta": {"version": 1, "status": "draft"}}
    new = {"meta": {"version": 2, "status": "draft"}}
    changes = diff_states(old, new)
    assert len(changes) == 1
    assert changes[0]["path"] == "meta.version"
    assert changes[0]["op"] == "changed"
    assert changes[0]["old"] == 1
    assert changes[0]["new"] == 2


def test_diff_states_nested_added_key():
    old = {"scope": {"include": ["feature_a"]}}
    new = {"scope": {"include": ["feature_a"], "exclude": ["legacy"]}}
    changes = diff_states(old, new)
    paths = [c["path"] for c in changes]
    assert "scope.exclude" in paths


def test_diff_states_list_element_changed():
    old = {"items": ["a", "b", "c"]}
    new = {"items": ["a", "X", "c"]}
    changes = diff_states(old, new)
    assert len(changes) == 1
    assert changes[0]["path"] == "items.1"
    assert changes[0]["op"] == "changed"
    assert changes[0]["old"] == "b"
    assert changes[0]["new"] == "X"


def test_diff_states_list_element_added():
    old = {"items": ["a", "b"]}
    new = {"items": ["a", "b", "c"]}
    changes = diff_states(old, new)
    assert any(c["op"] == "added" and c["path"] == "items.2" for c in changes)


def test_diff_states_list_element_removed():
    old = {"items": ["a", "b", "c"]}
    new = {"items": ["a", "b"]}
    changes = diff_states(old, new)
    assert any(c["op"] == "removed" and c["path"] == "items.2" for c in changes)


def test_diff_states_list_of_dicts():
    old = {"reqs": [{"id": "r1", "text": "Login page"}]}
    new = {"reqs": [{"id": "r1", "text": "Login page v2"}]}
    changes = diff_states(old, new)
    assert len(changes) == 1
    assert changes[0]["path"] == "reqs.0.text"
    assert changes[0]["op"] == "changed"


def test_diff_states_deep_nesting():
    old = {"a": {"b": {"c": {"d": "deep"}}}}
    new = {"a": {"b": {"c": {"d": "changed"}}}}
    changes = diff_states(old, new)
    assert len(changes) == 1
    assert changes[0]["path"] == "a.b.c.d"


def test_diff_states_empty_dicts():
    assert diff_states({}, {}) == []


def test_diff_states_old_empty():
    changes = diff_states({}, {"new_key": "value"})
    assert len(changes) == 1
    assert changes[0]["op"] == "added"


def test_diff_states_new_empty():
    changes = diff_states({"old_key": "value"}, {})
    assert len(changes) == 1
    assert changes[0]["op"] == "removed"


def test_diff_states_multiple_changes():
    old = {"a": 1, "b": 2, "c": 3}
    new = {"a": 10, "b": 2, "d": 4}
    changes = diff_states(old, new)
    ops = {c["op"] for c in changes}
    assert "changed" in ops  # a changed
    assert "removed" in ops  # c removed
    assert "added" in ops    # d added


# ── diff_summary ──────────────────────────────────────────────────────────────

def test_diff_summary_shape():
    old = {"title": "Old", "version": 1}
    new = {"title": "New", "version": 1, "extra": "field"}
    summary = diff_summary(old, new)
    assert "changes" in summary
    assert "added_fields" in summary
    assert "removed_fields" in summary
    assert "changed_fields" in summary
    assert "total_changes" in summary


def test_diff_summary_total_changes():
    old = {"a": 1, "b": 2}
    new = {"a": 99, "c": 3}
    summary = diff_summary(old, new)
    assert summary["total_changes"] == len(summary["changes"])


def test_diff_summary_added_fields():
    old = {}
    new = {"x": 1, "y": 2}
    summary = diff_summary(old, new)
    assert "x" in summary["added_fields"]
    assert "y" in summary["added_fields"]


def test_diff_summary_removed_fields():
    old = {"x": 1, "y": 2}
    new = {}
    summary = diff_summary(old, new)
    assert "x" in summary["removed_fields"]
    assert "y" in summary["removed_fields"]


def test_diff_summary_changed_fields():
    old = {"title": "Old"}
    new = {"title": "New"}
    summary = diff_summary(old, new)
    assert "title" in summary["changed_fields"]


def test_diff_summary_no_changes():
    state = {"a": 1, "b": {"c": 2}}
    summary = diff_summary(state, state)
    assert summary["total_changes"] == 0
    assert summary["changes"] == []


# ── detect_changes ────────────────────────────────────────────────────────────

def test_detect_changes_true_when_different():
    assert detect_changes({"a": 1}, {"a": 2}) is True


def test_detect_changes_false_when_same():
    assert detect_changes({"a": 1}, {"a": 1}) is False


def test_detect_changes_empty_dicts():
    assert detect_changes({}, {}) is False


def test_detect_changes_added_key():
    assert detect_changes({"a": 1}, {"a": 1, "b": 2}) is True


def test_detect_changes_nested():
    old = {"meta": {"phase": "discovery"}}
    new = {"meta": {"phase": "prd"}}
    assert detect_changes(old, new) is True
