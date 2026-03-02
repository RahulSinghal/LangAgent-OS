"""SoT patch engine.

Public API:
  apply_patch(state, patch) -> ProjectState
    - Validates patch keys against ProjectState schema (rejects unknown fields).
    - Merges patch into current state and returns a new validated model.
    - List fields in the patch REPLACE the existing list (not append).
      Agents that want to append must read the current list, extend it,
      and return the full updated list in their patch dict.
    - Raises ValueError on unknown fields or Pydantic validation failures.
"""

from __future__ import annotations

from pydantic import ValidationError

from app.sot.state import ProjectState


def apply_patch(state: ProjectState, patch: dict) -> ProjectState:
    """Merge *patch* into *state* and return a new validated ProjectState.

    Args:
        state:  Current Source of Truth.
        patch:  Dict of top-level ProjectState field names → new values.

    Returns:
        A new ProjectState instance with the patch applied.

    Raises:
        ValueError: Unknown patch key or Pydantic validation failure.
    """
    if not patch:
        return state

    known_fields = set(ProjectState.model_fields.keys())
    unknown = set(patch.keys()) - known_fields
    if unknown:
        raise ValueError(
            f"Patch contains unknown ProjectState fields: {sorted(unknown)}"
        )

    # Merge: start from current state serialized to python objects, overlay patch
    current = state.model_dump(mode="python")
    current.update(patch)

    try:
        return ProjectState(**current)
    except ValidationError as exc:
        raise ValueError(f"Patch produced invalid ProjectState: {exc}") from exc
