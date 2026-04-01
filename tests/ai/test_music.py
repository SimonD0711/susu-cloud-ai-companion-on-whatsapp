"""Tests for src.ai.search.music."""

import pytest
from unittest.mock import patch, MagicMock

from src.ai.search.music import ITunesMusic, SpotifyTracks, YouTubeVideos
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
    SPOTIFY_CLIENT_ID = ""
    SPOTIFY_CLIENT_SECRET = ""
    YOUTUBE_API_KEY = ""


def test_itunes_music_search_returns_empty_on_error():
    def mock_urlopen(req, timeout=None):
        raise Exception("Network error")

    cfg = MagicMock()
    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        itunes = ITunesMusic(cfg)
        results = itunes.search("周杰伦")
        assert results == []


def test_itunes_music_search_parses_response():
    mock_body = '{"results":[{"trackName":"晴天","artistName":"周杰伦","collectionName":"叶惠美","trackViewUrl":"https://x.com"}]}'

    def mock_urlopen(req, timeout=None):
        return MockResponse(mock_body.encode())

    cfg = MagicMock()
    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        itunes = ITunesMusic(cfg)
        results = itunes.search("周杰伦")
        assert len(results) == 1
        assert "晴天" in results[0].title
        assert results[0].source == "iTunes"


def test_spotify_returns_empty_without_credentials():
    spotify = SpotifyTracks(DummyConfig())
    assert spotify.search("test") == []


def test_spotify_token_fails_gracefully():
    def mock_urlopen(req, timeout=None):
        raise Exception("Auth error")

    cfg = MagicMock()
    cfg.SPOTIFY_CLIENT_ID = "bad"
    cfg.SPOTIFY_CLIENT_SECRET = "bad"

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        spotify = SpotifyTracks(cfg)
        assert spotify.search("test") == []


def test_youtube_returns_empty_without_api_key():
    yt = YouTubeVideos(DummyConfig())
    assert yt.search("music") == []


def test_youtube_search_returns_empty_on_error():
    def mock_urlopen(req, timeout=None):
        raise Exception("Network error")

    cfg = MagicMock()
    cfg.YOUTUBE_API_KEY = "test-key"

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        yt = YouTubeVideos(cfg)
        assert yt.search("test") == []
