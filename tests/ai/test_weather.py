"""Tests for src.ai.search.weather."""

import pytest
from unittest.mock import patch, MagicMock

from src.ai.search.weather import HKObservatory, OpenWeatherMap


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
    OPENWEATHER_API_KEY = ""
    TAVILY_API_KEY = ""


def test_hko_fetch_dataset_returns_none_on_error():
    def mock_urlopen(req, timeout=None):
        raise Exception("Network error")

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        hko = HKObservatory(DummyConfig())
        result = hko.fetch_dataset("rhu")
        assert result is None


def test_openweathermap_returns_none_without_api_key():
    owm = OpenWeatherMap(DummyConfig())
    assert owm.search("Hong Kong") is None


def test_openweathermap_search_calls_api():
    mock_body = '{"cod": 200, "name": "Hong Kong"}'

    def mock_urlopen(req, timeout=None):
        return MockResponse(mock_body.encode())

    cfg = MagicMock()
    cfg.OPENWEATHER_API_KEY = "test-key"

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        owm = OpenWeatherMap(cfg)
        result = owm.search("Hong Kong", "HK")
        assert result is not None
        assert result["cod"] == 200


def test_openweathermap_search_returns_none_on_failure():
    def mock_urlopen(req, timeout=None):
        raise Exception("API error")

    cfg = MagicMock()
    cfg.OPENWEATHER_API_KEY = "test-key"

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        owm = OpenWeatherMap(cfg)
        assert owm.search("UnknownCity", retries=1) is None
