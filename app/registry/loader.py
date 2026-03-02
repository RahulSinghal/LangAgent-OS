"""Agent registry loader — Phase 1D.

Loads and validates agents.yaml into AgentSpec Pydantic models.
The registry is cached at process startup — restart to pick up changes.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


# ── Schema ────────────────────────────────────────────────────────────────────

class AgentLimits(BaseModel):
    max_steps: int = 10
    max_tool_calls: int = 5
    budget_usd: float = 1.0


class AgentSpec(BaseModel):
    name: str
    role: str
    description: str
    capabilities: list[str] = Field(default_factory=list)
    required_inputs: list[str] = Field(default_factory=list)
    output_schema: str = ""
    prompt_template_path: str = ""
    allowed_tools: list[str] = Field(default_factory=list)
    limits: AgentLimits = Field(default_factory=AgentLimits)


# ── Loader ────────────────────────────────────────────────────────────────────

_YAML_PATH = Path(__file__).parent / "agents.yaml"


@lru_cache(maxsize=1)
def load_registry() -> dict[str, AgentSpec]:
    """Load agents.yaml and return a dict keyed by agent name.

    Cached after first call — restart the process to reload.

    Returns:
        Mapping of agent name → AgentSpec.

    Raises:
        FileNotFoundError: If agents.yaml does not exist.
        ValueError: If any agent entry fails Pydantic validation.
    """
    with _YAML_PATH.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    registry: dict[str, AgentSpec] = {}
    for entry in data.get("agents", []):
        spec = AgentSpec(**entry)
        registry[spec.name] = spec
    return registry


def get_agent_spec(name: str) -> AgentSpec:
    """Retrieve a single AgentSpec by name.

    Raises:
        KeyError: If the agent is not registered.
    """
    registry = load_registry()
    if name not in registry:
        raise KeyError(f"Agent '{name}' not found in registry")
    return registry[name]
