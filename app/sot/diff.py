"""SoT diff utilities — Phase 3D.

Computes recursive, field-level diffs between two ProjectState snapshots.
Used by the change control service to build ChangeRequest records.
"""

from __future__ import annotations


# ── Core recursive differ ──────────────────────────────────────────────────────

def diff_states(old: dict, new: dict, path: str = "") -> list[dict]:
    """Recursively compute a field-level diff between two dicts.

    Returns a list of change records, each shaped as one of::

        {"path": "requirements.0.text", "op": "changed", "old": ..., "new": ...}
        {"path": "requirements.2",      "op": "added",   "new": ...}
        {"path": "requirements.1",      "op": "removed", "old": ...}

    Both *old* and *new* may contain nested dicts and lists.
    List elements are compared by index.
    """
    changes: list[dict] = []

    old_keys = set(old.keys()) if isinstance(old, dict) else set()
    new_keys = set(new.keys()) if isinstance(new, dict) else set()

    # Keys present in old but gone from new
    for key in old_keys - new_keys:
        field_path = f"{path}.{key}" if path else str(key)
        changes.append({"path": field_path, "op": "removed", "old": old[key]})

    # Keys present in new but not in old
    for key in new_keys - old_keys:
        field_path = f"{path}.{key}" if path else str(key)
        changes.append({"path": field_path, "op": "added", "new": new[key]})

    # Keys present in both
    for key in old_keys & new_keys:
        field_path = f"{path}.{key}" if path else str(key)
        old_val = old[key]
        new_val = new[key]

        if isinstance(old_val, dict) and isinstance(new_val, dict):
            # Recurse into nested dicts
            changes.extend(diff_states(old_val, new_val, path=field_path))
        elif isinstance(old_val, list) and isinstance(new_val, list):
            # Compare lists element-by-element by index
            max_len = max(len(old_val), len(new_val))
            for idx in range(max_len):
                elem_path = f"{field_path}.{idx}"
                if idx >= len(old_val):
                    changes.append({"path": elem_path, "op": "added", "new": new_val[idx]})
                elif idx >= len(new_val):
                    changes.append({"path": elem_path, "op": "removed", "old": old_val[idx]})
                else:
                    old_elem = old_val[idx]
                    new_elem = new_val[idx]
                    if isinstance(old_elem, dict) and isinstance(new_elem, dict):
                        changes.extend(diff_states(old_elem, new_elem, path=elem_path))
                    elif old_elem != new_elem:
                        changes.append(
                            {"path": elem_path, "op": "changed", "old": old_elem, "new": new_elem}
                        )
        else:
            if old_val != new_val:
                changes.append(
                    {"path": field_path, "op": "changed", "old": old_val, "new": new_val}
                )

    return changes


# ── Summary helper ─────────────────────────────────────────────────────────────

def diff_summary(old_state: dict, new_state: dict) -> dict:
    """Return a structured diff summary between two state dicts.

    Shape::

        {
          "changes":        list[dict],   # from diff_states
          "added_fields":   list[str],
          "removed_fields": list[str],
          "changed_fields": list[str],
          "total_changes":  int,
        }
    """
    changes = diff_states(old_state, new_state)

    added_fields: list[str] = [c["path"] for c in changes if c["op"] == "added"]
    removed_fields: list[str] = [c["path"] for c in changes if c["op"] == "removed"]
    changed_fields: list[str] = [c["path"] for c in changes if c["op"] == "changed"]

    return {
        "changes": changes,
        "added_fields": added_fields,
        "removed_fields": removed_fields,
        "changed_fields": changed_fields,
        "total_changes": len(changes),
    }


# ── Boolean shortcut ───────────────────────────────────────────────────────────

def detect_changes(old_state: dict, new_state: dict) -> bool:
    """Return True if any substantive field changed between the two states."""
    return len(diff_states(old_state, new_state)) > 0
