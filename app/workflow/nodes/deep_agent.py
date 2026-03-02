"""Deep agent subgraph node — Phase 2 implementation.

Guarded subgraph: bounded plan-act-observe loop.
Budgets enforced: max_steps, max_tool_calls, cost_usd.
All tool calls go through Tool Gateway.
"""

# Phase 2: implement deep_agent_node(state) -> dict
