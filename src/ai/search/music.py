"""Music search providers: iTunes, Spotify, YouTube."""

from __future__ import annotations

import base64
import json
import re
import threading
from typing import Optional

from src.ai.config import AIConfig
from src.ai.search.router import SearchResult


class ITunesMusic:
    """iTunes Search API."""

    def __init__(self, config: AIConfig):
        self.config = config

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        limit = min(limit, 10)
        try:
            import urllib.request
            import urllib.parse
            params = urllib.parse.urlencode({
                "term": query,
                "entity": "song",
                "country": "HK",
                "lang": "zh_Hant",
                "limit": limit,
            })
            url = f"https://itunes.apple.com/search?{params}"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            results = []
            for item in (data.get("results") or [])[:limit]:
                artist = item.get("artistName", "")
                track = item.get("trackName", "")
                album = item.get("collectionName", "")
                title = f"{track} - {artist}" if artist else track
                snippet = f"{artist} / {album}" if album else artist
                results.append(SearchResult(
                    title=title,
                    snippet=snippet,
                    url=item.get("trackViewUrl", ""),
                    source="iTunes",
                    published_at=None,
                ))
            return results
        except Exception:
            return []


class SpotifyTracks:
    """Spotify Web API search."""

    def __init__(self, config: AIConfig):
        self.config = config
        self._token_cache: Optional[str] = None
        self._token_expiry: float = 0
        self._lock = threading.Lock()

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        if not self.config.SPOTIFY_CLIENT_ID or not self.config.SPOTIFY_CLIENT_SECRET:
            return []

        limit = min(limit, 10)
        token = self._get_token()
        if not token:
            return []

        try:
            import urllib.request
            import urllib.parse
            params = urllib.parse.urlencode({"q": query, "type": "track", "limit": limit})
            url = f"https://api.spotify.com/v1/search?{params}"
            req = urllib.request.Request(
                url,
                headers={"Authorization": f"Bearer {token}"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            results = []
            for item in (data.get("tracks", {}).get("items") or [])[:limit]:
                artists = ", ".join(a.get("name", "") for a in item.get("artists", []))
                album = item.get("album", {}).get("name", "")
                title = f"{item.get('name', '')} - {artists}"
                snippet = f"{artists} / {album}"
                results.append(SearchResult(
                    title=title,
                    snippet=snippet,
                    url=item.get("external_urls", {}).get("spotify", ""),
                    source="Spotify",
                    published_at=None,
                ))
            return results
        except Exception:
            return []

    def _get_token(self) -> Optional[str]:
        import time
        with self._lock:
            if self._token_cache and time.time() < self._token_expiry:
                return self._token_cache
            try:
                import urllib.request
                creds = base64.b64encode(
                    f"{self.config.SPOTIFY_CLIENT_ID}:{self.config.SPOTIFY_CLIENT_SECRET}".encode()
                ).decode()
                req = urllib.request.Request(
                    "https://accounts.spotify.com/api/token",
                    data=b"grant_type=client_credentials",
                    headers={"Authorization": f"Basic {creds}", "Content-Type": "application/x-www-form-urlencoded"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    token_data = json.loads(resp.read().decode("utf-8"))
                self._token_cache = token_data.get("access_token")
                self._token_expiry = time.time() + (token_data.get("expires_in", 3600) - 60)
                return self._token_cache
            except Exception:
                return None


class YouTubeVideos:
    """YouTube Data API v3 search."""

    def __init__(self, config: AIConfig):
        self.config = config

    def search(
        self,
        query: str,
        limit: int = 5,
        order: str = "date",
        published_after_days: Optional[int] = None,
    ) -> list[SearchResult]:
        api_key = self.config.YOUTUBE_API_KEY
        if not api_key:
            return []

        limit = min(limit, 10)
        try:
            import urllib.request
            import urllib.parse
            import time
            params = {
                "part": "snippet",
                "q": query,
                "type": "video",
                "order": order,
                "maxResults": limit,
                "regionCode": "HK",
                "relevanceLanguage": "zh-Hant",
                "key": api_key,
            }
            if published_after_days:
                from datetime import datetime, timezone
                dt = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=published_after_days)
                params["publishedAfter"] = dt.isoformat().replace("+00:00", "Z")

            url = f"https://www.googleapis.com/youtube/v3/search?{urllib.parse.urlencode(params)}"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            results = []
            for item in (data.get("items") or [])[:limit]:
                snippet = item.get("snippet", {})
                video_id = item.get("id", {}).get("videoId", "")
                results.append(SearchResult(
                    title=snippet.get("title", ""),
                    snippet=snippet.get("description", "")[:200],
                    url=f"https://www.youtube.com/watch?v={video_id}",
                    source="YouTube",
                    published_at=snippet.get("publishedAt", ""),
                ))
            return results
        except Exception:
            return []


from datetime import timedelta
