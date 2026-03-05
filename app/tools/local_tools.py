"""Local tool implementations.

All tools follow the signature:  fn(payload: dict) -> Any

Phase 1 tools:
  read_file   — read a local file by path
  write_file  — write content to a local file

Phase 2 tools:
  web_search  — keyword search via Tavily API (falls back to stubs when
                TAVILY_API_KEY is not set)
  fetch_url   — fetch URL content via httpx (falls back to stub when httpx
                is not installed or FETCH_URL_TIMEOUT == 0)

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
    """Phase 2: Web search — uses Tavily API when TAVILY_API_KEY is set,
    otherwise returns deterministic stub results.

    Payload keys:
        query       (str): Search query string.
        max_results (int, optional): Max number of results (default 5).

    Returns:
        list of {title, url, snippet} dicts.
    """
    query = payload.get("query", "")
    max_results = int(payload.get("max_results", 5))

    try:
        from app.core.config import settings
        api_key = settings.TAVILY_API_KEY
    except Exception:
        api_key = ""

    if api_key:
        try:
            import httpx
            resp = httpx.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": api_key,
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "basic",
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": r.get("content", ""),
                }
                for r in data.get("results", [])[:max_results]
            ]
        except Exception:
            pass  # fall through to stub

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
    """Phase 2: Fetch URL content via httpx, falling back to a stub when httpx
    is not installed or FETCH_URL_TIMEOUT is 0.

    Payload keys:
        url     (str): URL to fetch.
        timeout (int, optional): Override request timeout in seconds.

    Returns:
        Page text content as a string.
    """
    url = payload.get("url", "")

    try:
        from app.core.config import settings
        timeout = int(payload.get("timeout", settings.FETCH_URL_TIMEOUT))
    except Exception:
        timeout = int(payload.get("timeout", 10))

    if timeout == 0:
        return (
            f"[STUB] Content fetched from {url}\n\n"
            "Set FETCH_URL_TIMEOUT > 0 to enable real HTTP fetching."
        )

    try:
        import httpx
        resp = httpx.get(url, timeout=timeout, follow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except ImportError:
        return (
            f"[STUB] Content fetched from {url}\n\n"
            "Install httpx (`pip install httpx`) to enable real URL fetching."
        )
    except Exception as exc:
        return f"[ERROR] Failed to fetch {url}: {exc}"


# ── Registry ──────────────────────────────────────────────────────────────────

TOOL_REGISTRY: dict[str, Callable[[dict], Any]] = {
    "read_file":  _read_file,
    "write_file": _write_file,
    "web_search": _web_search,   # Phase 2
    "fetch_url":  _fetch_url,    # Phase 2
}
