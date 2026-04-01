"""News search providers: Tavily, Google News, Bing News, Reddit, X/Twitter."""

from __future__ import annotations

import json
import re
import time
from typing import Optional, Any

from src.ai.config import AIConfig
from src.ai.search.router import SearchResult


class TavilyNews:
    """Tavily news search API."""

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
                "topic": "news",
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
                    published_at=item.get("published_date", ""),
                ))
            return results
        except Exception:
            return []


class GoogleNews:
    """Google News RSS feed."""

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        try:
            import urllib.request
            import urllib.parse
            encoded_query = urllib.parse.quote(query)
            url = f"https://news.google.com/rss/search?q={encoded_query}&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=15) as resp:
                xml_text = resp.read().decode("utf-8")
            return self._parse(xml_text, limit)
        except Exception:
            return []

    def _parse(self, xml_text: str, limit: int) -> list[SearchResult]:
        import xml.etree.ElementTree as ET
        try:
            root = ET.fromstring(xml_text)
        except Exception:
            return []

        results = []
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for item in root.findall(".//item")[:limit]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            description = (item.findtext("description") or "").strip()
            pub_date = (item.findtext("pubDate") or "").strip()
            results.append(SearchResult(
                title=title,
                snippet=description,
                url=link,
                source="Google News",
                published_at=pub_date,
            ))
        return results


class BingNews:
    """Bing News Search API v7."""

    def __init__(self, config: AIConfig):
        self.config = config

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        api_key = self.config.BING_API_KEY
        if not api_key:
            return []

        limit = min(limit, 10)
        try:
            import urllib.request
            import urllib.parse
            params = urllib.parse.urlencode({
                "q": query,
                "mkt": "zh-HK",
                "count": limit,
                "freshness": "Day",
            })
            url = f"https://api.bing.microsoft.com/v7.0/news/search?{params}"
            req = urllib.request.Request(
                url,
                headers={"Ocp-Apim-Subscription-Key": api_key},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            results = []
            for item in (data.get("value") or [])[:limit]:
                results.append(SearchResult(
                    title=item.get("name", ""),
                    snippet=item.get("description", ""),
                    url=item.get("url", ""),
                    source="Bing News",
                    published_at=item.get("datePublished", ""),
                ))
            return results
        except Exception:
            return []


class RedditSearch:
    """Reddit search via search.json API."""

    def __init__(self, config: AIConfig):
        self.config = config

    def search(self, query: str, limit: int = 5, sort: str = "relevance") -> list[SearchResult]:
        limit = min(limit, 10)
        try:
            import urllib.request
            import urllib.parse
            params = urllib.parse.urlencode({
                "q": query,
                "sort": sort,
                "limit": limit,
                "restrict_sr": 1,
            })
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


class XSearch:
    """X/Twitter recent posts search."""

    def __init__(self, config: AIConfig):
        self.config = config

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        bearer = self.config.X_BEARER_TOKEN
        if not bearer:
            return []

        limit = min(limit, 10)
        clean_query = re.sub(r"\s*from:\S+", "", query).strip()
        clean_query = re.sub(r"\s*#\S+", "", clean_query).strip()
        if not clean_query:
            return []
        clean_query = f"({clean_query}) -is:retweet"

        try:
            import urllib.request
            import urllib.parse
            params = urllib.parse.urlencode({
                "query": clean_query,
                "max_results": limit,
                "tweet.fields": "created_at,lang,author_id",
                "expansions": "author_id",
            })
            url = f"https://api.twitter.com/2/tweets/search/recent?{params}"
            req = urllib.request.Request(
                url,
                headers={"Authorization": f"Bearer {bearer}"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            users = {u["id"]: u["username"] for u in data.get("includes", {}).get("users", [])}
            results = []
            for tweet in (data.get("data") or [])[:limit]:
                author = users.get(tweet.get("author_id", ""), "unknown")
                text = tweet.get("text", "")
                results.append(SearchResult(
                    title=text[:100],
                    snippet=text,
                    url=f"https://twitter.com/{author}/status/{tweet.get('id')}",
                    source="X",
                    published_at=tweet.get("created_at", ""),
                ))
            return results
        except Exception:
            return []
