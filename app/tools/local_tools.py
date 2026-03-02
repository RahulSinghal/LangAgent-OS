"""Local tool implementations.

All tools follow the signature:  fn(payload: dict) -> Any

Phase 1 tools:
  read_file   — read a local file by path
  write_file  — write content to a local file

Phase 2 tools (stubs — will call real APIs when keys are configured):
  web_search  — keyword search returning mock results (stub)
  fetch_url   — fetch URL content, return as text (stub)

Phase 3 additions: mcp_adapter tools
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


# ── Tool implementations ──────────────────────────────────────────────────────

def _read_file(payload: dict) -> str:
    """Read a local file.

    Payload keys:
        path (str): Absolute or relative path to read.
    """
    path = Path(payload["path"])
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    return path.read_text(encoding="utf-8")


def _write_file(payload: dict) -> str:
    """Write content to a local file, creating parent dirs as needed.

    Payload keys:
        path    (str): Destination path.
        content (str): Text to write.
    """
    path = Path(payload["path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload["content"], encoding="utf-8")
    return f"Written {len(payload['content'])} chars to {path}"


def _web_search(payload: dict) -> list[dict]:
    """Phase 2: Web search stub — returns deterministic mock results.

    Payload keys:
        query       (str): Search query string.
        max_results (int, optional): Max number of results (default 5).

    Returns:
        list of {title, url, snippet} dicts.

    Note: Replace with real Tavily/SerpAPI integration when API keys are set.
    """
    query = payload.get("query", "")
    max_results = int(payload.get("max_results", 5))

    stub_results = [
        {
            "title": f"Analysis of '{query}' — Market Overview",
            "url": f"https://example.com/market/{query.replace(' ', '-').lower()}",
            "snippet": (
                f"Comprehensive analysis of {query} showing market trends, "
                "vendor landscape, and build-vs-buy considerations."
            ),
        },
        {
            "title": f"Top vendors for {query}",
            "url": f"https://example.com/vendors/{query.replace(' ', '-').lower()}",
            "snippet": (
                f"Leading commercial solutions for {query} include SaaS platforms "
                "and open-source alternatives with varying licensing models."
            ),
        },
        {
            "title": f"Open-source alternatives for {query}",
            "url": f"https://github.com/topics/{query.replace(' ', '-').lower()}",
            "snippet": (
                f"Active open-source projects addressing {query} use cases, "
                "with active communities and enterprise support options."
            ),
        },
    ]
    return stub_results[:max_results]


def _fetch_url(payload: dict) -> str:
    """Phase 2: URL fetch stub — returns mock content for the given URL.

    Payload keys:
        url     (str): URL to fetch.
        timeout (int, optional): Request timeout in seconds (default 10).

    Returns:
        Page content as a string.

    Note: Replace with real httpx/requests call when needed.
    """
    url = payload.get("url", "")
    return (
        f"[STUB] Content fetched from {url}\n\n"
        "This is a stub response. Configure real HTTP fetching "
        "by replacing _fetch_url with an httpx implementation."
    )


# ── Registry ──────────────────────────────────────────────────────────────────

TOOL_REGISTRY: dict[str, Callable[[dict], Any]] = {
    "read_file":  _read_file,
    "write_file": _write_file,
    "web_search": _web_search,   # Phase 2
    "fetch_url":  _fetch_url,    # Phase 2
}
