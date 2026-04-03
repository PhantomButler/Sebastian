from __future__ import annotations

from typing import Any

import httpx

from sebastian.core.tool import tool
from sebastian.core.types import ToolResult


@tool(
    name="web_search",
    description=(
        "Search the web using DuckDuckGo and return a list of results "
        "with titles and snippets."
    ),
    requires_approval=False,
    permission_level="owner",
)
async def web_search(query: str) -> ToolResult:
    url = "https://api.duckduckgo.com/"
    params = {"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        results: list[dict[str, Any]] = []
        if data.get("AbstractText"):
            results.append({
                "title": data.get("Heading", ""),
                "snippet": data["AbstractText"],
                "url": data.get("AbstractURL", ""),
            })
        for rel in data.get("RelatedTopics", [])[:5]:
            if isinstance(rel, dict) and "Text" in rel:
                results.append({
                    "title": rel.get("Text", "")[:100],
                    "snippet": rel.get("Text", ""),
                    "url": rel.get("FirstURL", ""),
                })
        return ToolResult(ok=True, output={"query": query, "results": results})
    except Exception as e:
        return ToolResult(ok=False, error=str(e))
