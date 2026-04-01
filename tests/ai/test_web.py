"""Tests for src.ai.search.web."""

import pytest
from unittest.mock import patch, MagicMock

from src.ai.search.web import TavilyWeb, BingWeb, DuckDuckGoWeb


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
    REDDIT_USER_AGENT = "TestAgent/1.0"


def test_tavily_web_returns_empty_without_api_key():
    tavily = TavilyWeb(DummyConfig())
    assert tavily.search("test") == []


def test_tavily_web_parses_response():
    mock_body = '{"results":[{"title":"Web Page","content":"Content","url":"https://x.com"}]}'

    def mock_urlopen(req, timeout=None):
        return MockResponse(mock_body.encode())

    cfg = MagicMock()
    cfg.TAVILY_API_KEY = "test-key"

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        tavily = TavilyWeb(cfg)
        results = tavily.search("test")
        assert len(results) == 1
        assert results[0].title == "Web Page"
        assert results[0].source == "Tavily"


def test_bing_web_returns_empty_without_api_key():
    bing = BingWeb(DummyConfig())
    assert bing.search("test") == []


def test_bing_web_parses_response():
    mock_body = '{"webPages":{"value":[{"name":"Bing Page","snippet":"Snippet","url":"https://bing.com"}]}}'

    def mock_urlopen(req, timeout=None):
        return MockResponse(mock_body.encode())

    cfg = MagicMock()
    cfg.BING_API_KEY = "test-key"

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        bing = BingWeb(cfg)
        results = bing.search("test")
        assert len(results) == 1
        assert results[0].source == "Bing"


def test_duckduckgo_returns_empty_on_error():
    def mock_urlopen(req, timeout=None):
        raise Exception("Network error")

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        ddg = DuckDuckGoWeb()
        assert ddg.search("test") == []
