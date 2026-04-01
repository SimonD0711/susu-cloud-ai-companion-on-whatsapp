"""Web search providers: Tavily, Bing, DuckDuckGo, Reddit."""

from __future__ import annotations

import html
import json
import re
import urllib.parse
from typing import Optional

from src.ai.config import AIConfig
from src.ai.search.router import SearchResult


class TavilyWeb:
    """Tavily web search API."""

    def __init__(self, config: AIConfig):
        self.config = config

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        api_key = self.config.TAVILY_API_KEY
        if not api_key:
            return []

        limit = min(limit, 10)
        try:
            import urllib.request
            url = "https://api.tavily.com/search"
            payload = json.dumps({
                "query": query,
                "search_depth": "basic",
                "max_results": limit,
            }).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            results = []
            for item in (data.get("results") or [])[:limit]:
                results.append(SearchResult(
                    title=item.get("title", ""),
                    snippet=item.get("content", ""),
                    url=item.get("url", ""),
                    source="Tavily",
                    published_at=item.get("published_date"),
                ))
            return results
        except Exception:
            return []


class BingWeb:
    """Bing Web Search API v7."""

    def __init__(self, config: AIConfig):
        self.config = config

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        api_key = self.config.BING_API_KEY
        if not api_key:
            return []

        limit = min(limit, 10)
        try:
            import urllib.request
            params = urllib.parse.urlencode({
                "q": query,
                "mkt": "zh-HK",
                "count": limit,
            })
            url = f"https://api.bing.microsoft.com/v7.0/search?{params}"
            req = urllib.request.Request(
                url,
                headers={"Ocp-Apim-Subscription-Key": api_key},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            results = []
            for item in (data.get("webPages", {}).get("value") or [])[:limit]:
                results.append(SearchResult(
                    title=item.get("name", ""),
                    snippet=item.get("snippet", ""),
                    url=item.get("url", ""),
                    source="Bing",
                    published_at=None,
                ))
            return results
        except Exception:
            return []


class DuckDuckGoWeb:
    """DuckDuckGo HTML search page scraper."""

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        try:
            import urllib.request
            import urllib.parse
            url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                html_text = resp.read().decode("utf-8")
            return self._parse(html_text, limit)
        except Exception:
            return []

    def _parse(self, html_text: str, limit: int) -> list[SearchResult]:
        results = []
        for match in re.finditer(
            r'<a class="result__a" href="([^"]+)"[^>]*>(.*?)</a>.*?<a class="result__snippet"[^>]*>(.*?)</a>',
            html_text,
            re.DOTALL,
        )[:limit]:
            url = self._decode_url(match.group(1))
            title = re.sub(r"<[^>]+>", "", match.group(2)).strip()
            snippet = re.sub(r"<[^>]+>", "", match.group(3)).strip()
            results.append(SearchResult(
                title=title,
                snippet=snippet,
                url=url,
                source="DuckDuckGo",
                published_at=None,
            ))
        return results

    def _decode_url(self, raw_url: str) -> str:
        value = html.unescape(raw_url or "").strip()
        if value.startswith("//"):
            value = "https:" + value
        parsed = urllib.parse.urlparse(value)
        if parsed.netloc.endswith("duckduckgo.com"):
            params = urllib.parse.parse_qs(parsed.query)
            target = params.get("uddg", [""])[0]
            if target:
                return html.unescape(urllib.parse.unquote(target))
        return value


class RedditWeb:
    """Reddit search (fallback when API unavailable)."""

    def __init__(self, config: AIConfig):
        self.config = config

    def search(self, query: str, limit: int = 5, sort: str = "relevance") -> list[SearchResult]:
        limit = min(limit, 10)
        try:
            import urllib.request
            import urllib.parse
            params = urllib.parse.urlencode({"q": query, "sort": sort, "restrict_sr": 1})
            url = f"https://www.reddit.com/search/search.json?{params}"
            req = urllib.request.Request(
                url,
                headers={"User-Agent": self.config.REDDIT_USER_AGENT},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            results = []
            for child in (data.get("data", {}).get("children", []))[:limit]:
                post = child.get("data", {})
                permalink = "https://reddit.com" + post.get("permalink", "")
                results.append(SearchResult(
                    title=post.get("title", ""),
                    snippet=post.get("selftext", "")[:200],
                    url=permalink,
                    source="Reddit",
                    published_at=post.get("created_utc", ""),
                ))
            return results
        except Exception:
            return []
