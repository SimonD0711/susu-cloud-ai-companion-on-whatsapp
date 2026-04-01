"""Tests for src.ai.search.router."""

import pytest

from src.ai.search.router import SearchRouter, SearchPlan, SearchResult


def test_search_plan_defaults():
    plan = SearchPlan(should_search=True, mode="weather", query="香港天气", confidence=0.8)
    assert plan.should_search is True
    assert plan.mode == "weather"
    assert plan.query == "香港天气"
    assert plan.confidence == 0.8
    assert plan.source == "router"


def test_search_result_fields():
    r = SearchResult(title="Test", snippet="Desc", url="https://x.com", source="X", published_at="2026-01-01")
    assert r.title == "Test"
    assert r.snippet == "Desc"
    assert r.url == "https://x.com"
    assert r.source == "X"


def test_search_result_optional_published_at():
    r = SearchResult(title="T", snippet="S", url="https://x.com", source="X")
    assert r.published_at is None


def test_router_detect_weather_query():
    config = pytest.importorskip("src.ai.config").AIConfig()
    llm = None
    router = SearchRouter(llm, config)
    assert router._detect_mode("今日天氣點樣") == "weather"
    assert router._detect_mode("溫度幾多度") == "weather"


def test_router_detect_music_query():
    config = pytest.importorskip("src.ai.config").AIConfig()
    llm = None
    router = SearchRouter(llm, config)
    assert router._detect_mode("我想聽歌") == "music"
    assert router._detect_mode("播放周杰倫") == "music"


def test_router_detect_news_query():
    config = pytest.importorskip("src.ai.config").AIConfig()
    llm = None
    router = SearchRouter(llm, config)
    assert router._detect_mode("今日新聞") == "news"
    assert router._detect_mode("最新消息") == "news"


def test_router_detect_unknown_query():
    config = pytest.importorskip("src.ai.config").AIConfig()
    llm = None
    router = SearchRouter(llm, config)
    assert router._detect_mode("你好嗎") == "unknown"


def test_router_clean_text():
    config = pytest.importorskip("src.ai.config").AIConfig()
    router = SearchRouter(None, config)
    assert router._clean_text("你好   世界") == "你好 世界"
    assert router._clean_text("  你好  ") == "你好"


def test_router_dedupe_terms():
    config = pytest.importorskip("src.ai.config").AIConfig()
    router = SearchRouter(None, config)
    assert router._dedupe_terms("香港 天氣 香港") == "香港 天氣"
    assert router._dedupe_terms("a b a c") == "a b c"


def test_router_score_result():
    config = pytest.importorskip("src.ai.config").AIConfig()
    router = SearchRouter(None, config)
    r = SearchResult(title="天氣預報", snippet="香港天氣", url="https://news.com", source="News")
    score = router._score_result(r, "news", "天氣", 0)
    assert score > 50


def test_router_review_deduplicates():
    config = pytest.importorskip("src.ai.config").AIConfig()
    router = SearchRouter(None, config)
    results = [
        SearchResult(title="A", snippet="S", url="https://x.com", source="X"),
        SearchResult(title="B", snippet="S", url="https://x.com", source="X"),
        SearchResult(title="C", snippet="S", url="https://y.com", source="Y"),
    ]
    reviewed = router.review(results, "news", "test")
    assert len(reviewed) == 2
    urls = {r.url for r in reviewed}
    assert "https://x.com" in urls
    assert "https://y.com" in urls
