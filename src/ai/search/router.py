"""Search router: LLM-based query routing and result aggregation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional, Any

from src.ai.config import AIConfig
from src.ai.llm.manager import LLMManager


@dataclass
class SearchResult:
    """A single search result."""
    title: str
    snippet: str
    url: str
    source: str
    published_at: Optional[str] = None


@dataclass
class SearchPlan:
    """A search plan from the router."""
    should_search: bool
    mode: str
    query: str
    confidence: float
    source: str = "router"


class SearchRouter:
    """Routes search queries to appropriate providers using LLM judgment."""

    MODE_KEYWORDS = {
        "weather": ["天氣", "天氣預報", "溫度", "下雨", "地震", " typhoon", "天災"],
        "news": ["新聞", "最新", "報導", "消息", "時事"],
        "music": ["歌", "音樂", "聽歌", "播放", "歌曲", "專輯"],
        "web": [],
    }

    EXPLICIT_HINTS = {
        "weather": ["天氣", "溫度", "下雨", "颱風", "地震"],
        "news": ["新聞", "最新消息", "時事"],
        "music": ["歌", "音樂", "播放", "歌曲"],
    }

    def __init__(self, llm_manager: LLMManager, config: AIConfig):
        self.llm = llm_manager
        self.config = config

    def route(self, incoming_text: str) -> Optional[SearchPlan]:
        """
        Route a user query to the appropriate search mode.

        Args:
            incoming_text: Raw user input text.

        Returns:
            SearchPlan if search is needed, None otherwise.
        """
        text = self._clean_text(incoming_text)
        if not text:
            return None

        hinted_mode = self._detect_mode(text)

        if hinted_mode == "weather":
            query = self._dedupe_terms(text)
        elif hinted_mode in ("news", "music"):
            query = self._extract_query(text, mode=hinted_mode)
        else:
            query = self._extract_query(text, mode="web")

        prompt = self._build_router_prompt(text, hinted_mode, query)
        raw = self._call_router_llm(prompt)
        data = self._parse_router_response(raw)

        if not data:
            return self._explicit_fallback(text)

        should_search = bool(data.get("should_search"))
        mode = self._clean_text(data.get("mode", "")).lower()
        if mode not in {"weather", "news", "music", "web"}:
            mode = "none"

        query = self._dedupe_terms(self._normalize_entities(data.get("query") or ""))
        try:
            confidence = float(data.get("confidence", 0) or 0)
        except Exception:
            confidence = 0.0

        if should_search and mode in {"weather", "news", "music", "web"}:
            return SearchPlan(
                should_search=True,
                mode=mode,
                query=query,
                confidence=max(0.0, min(confidence, 1.0)),
                source="router",
            )

        return self._explicit_fallback(text)

    def review(
        self,
        results: list[SearchResult],
        mode: str,
        query: str,
    ) -> list[SearchResult]:
        """
        Review and filter search results using LLM.

        Args:
            results: List of search results.
            mode: Search mode (weather, news, music, web).
            query: Original search query.

        Returns:
            Filtered and ranked results.
        """
        if not results:
            return []

        scored = []
        for i, item in enumerate(results):
            score = self._score_result(item, mode, query, i)
            scored.append((score, item))

        scored.sort(key=lambda x: x[0], reverse=True)

        seen_urls = set()
        deduped = []
        for score, item in scored:
            url_key = item.url.lower()
            if url_key not in seen_urls:
                seen_urls.add(url_key)
                deduped.append(item)

        return deduped

    def _detect_mode(self, text: str) -> str:
        """Detect search mode from text using keywords."""
        for mode, hints in self.MODE_KEYWORDS.items():
            for hint in hints:
                if hint in text.lower():
                    return mode
        return "unknown"

    def _explicit_fallback(self, text: str) -> Optional[SearchPlan]:
        """Fallback to explicit keyword detection."""
        mode = self._detect_mode(text)
        if not mode or mode == "unknown":
            return None

        if mode == "weather":
            query = self._dedupe_terms(text)
        elif mode == "news":
            query = self._build_news_query(self._extract_query(text, mode="web"))
        elif mode == "music":
            query = self._build_music_query(self._extract_query(text, mode="music"))
        else:
            query = self._dedupe_terms(self._normalize_entities(self._extract_query(text, mode="web")))

        return SearchPlan(
            should_search=True,
            mode=mode,
            query=query,
            confidence=0.35,
            source="explicit_fallback",
        )

    def _score_result(
        self,
        item: SearchResult,
        mode: str,
        query: str,
        index: int,
    ) -> int:
        """Score a search result for ranking."""
        score = max(0, 50 - index * 5)

        query_lower = query.lower()
        title_lower = item.title.lower()
        snippet_lower = item.snippet.lower()

        if query_lower in title_lower:
            score += 15
        if query_lower in snippet_lower:
            score += 5

        if mode == "news":
            if "news" in item.source.lower():
                score += 10
        elif mode == "music":
            if any(s in item.source.lower() for s in ["spotify", "itunes", "youtube"]):
                score += 10
        elif mode == "web":
            if any(s in item.url.lower() for s in ["wikipedia", "zhihu", "blog"]):
                score += 5

        return score

    def _build_router_prompt(self, text: str, hinted_mode: str, hinted_query: str) -> str:
        return f"""用戶訊息：{text}
目前香港時間：2026-04-01 10:00
高概率類別：{hinted_mode}
原句主體線索：{hinted_query}

請判斷呢句需唔需要查即時外部資料；如果要，就回傳最適合搜尋嘅 mode 同 query。
如果高概率類別已經係 news 或 music，除非非常明顯唔啱，否則應優先沿用。
query 要保留主體人物 / 地點 / 品牌名，唔好只輸出日期或者泛詞。"""

    def _call_router_llm(self, prompt: str) -> Optional[dict[str, Any]]:
        """Call LLM for router decision."""
        try:
            messages = [
                {"role": "system", "content": "You are a search routing assistant."},
                {"role": "user", "content": prompt},
            ]
            resp = self.llm.chat(messages, model=self.config.RELAY_MODEL, max_tokens=150, temperature=0.1)
            import json as _json
            return _json.loads(resp.content)
        except Exception:
            return None

    def _parse_router_response(self, raw: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        if not raw:
            return None
        return raw

    def _clean_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    def _dedupe_terms(self, text: str) -> str:
        words = text.split()
        seen = set()
        result = []
        for w in words:
            if w.lower() not in seen:
                seen.add(w.lower())
                result.append(w)
        return " ".join(result)

    def _normalize_entities(self, text: str) -> str:
        return self._clean_text(text)

    def _extract_query(self, text: str, mode: str = "web") -> str:
        """Extract search query from user text."""
        text = self._clean_text(text)
        text = re.sub(r"^(天氣|天氣預報|天氣查詢|溫度|下雨|颱風|地震|新聞|最新消息|時事|搵歌|聽歌|播放|歌曲|音樂|search|search for|find|播放|搵)", "", text, flags=re.IGNORECASE)
        return self._dedupe_terms(text)

    def _build_news_query(self, query: str) -> str:
        return f"{query} 新聞"

    def _build_music_query(self, query: str) -> str:
        return query
