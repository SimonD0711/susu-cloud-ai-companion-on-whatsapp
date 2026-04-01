"""Tests for src.ai.search.news."""

import pytest
from unittest.mock import patch, MagicMock

from src.ai.search.news import TavilyNews, GoogleNews, BingNews, RedditSearch, XSearch
from src.ai.search.router import SearchResult


class MockResponse:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class DummyConfig:
    TAVILY_API_KEY = ""
    BING_API_KEY = ""
    X_BEARER_TOKEN = ""
    REDDIT_USER_AGENT = "TestAgent/1.0"
    SPOTIFY_CLIENT_ID = ""
    SPOTIFY_CLIENT_SECRET = ""
    YOUTUBE_API_KEY = ""


def test_tavily_news_returns_empty_without_api_key():
    tavily = TavilyNews(DummyConfig())
    assert tavily.search("news") == []


def test_tavily_news_parses_response():
    mock_body = '{"results":[{"title":"Test News","content":"Description","url":"https://x.com"}]}'

    def mock_urlopen(req, timeout=None):
        return MockResponse(mock_body.encode())

    cfg = MagicMock()
    cfg.TAVILY_API_KEY = "test-key"

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        tavily = TavilyNews(cfg)
        results = tavily.search("test")
        assert len(results) == 1
        assert results[0].title == "Test News"
        assert results[0].source == "Tavily"


def test_bing_news_returns_empty_without_api_key():
    bing = BingNews(DummyConfig())
    assert bing.search("news") == []


def test_bing_news_parses_response():
    mock_body = '{"value":[{"name":"Bing News","description":"Desc","url":"https://bing.com","datePublished":"2026-01-01"}]}'

    def mock_urlopen(req, timeout=None):
        return MockResponse(mock_body.encode())

    cfg = MagicMock()
    cfg.BING_API_KEY = "test-key"

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        bing = BingNews(cfg)
        results = bing.search("news")
        assert len(results) == 1
        assert results[0].source == "Bing News"


def test_google_news_returns_empty_on_error():
    def mock_urlopen(req, timeout=None):
        raise Exception("Network error")

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        gn = GoogleNews()
        assert gn.search("news") == []


def test_reddit_search_returns_empty_without_api_key():
    cfg = MagicMock()
    cfg.REDDIT_USER_AGENT = ""
    reddit = RedditSearch(cfg)
    assert reddit.search("test") == []


def test_x_search_returns_empty_without_bearer():
    x = XSearch(DummyConfig())
    assert x.search("test") == []
