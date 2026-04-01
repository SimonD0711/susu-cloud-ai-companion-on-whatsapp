"""Tests for src.ai.whisper.groq."""

import pytest
from unittest.mock import patch

from src.ai.whisper.groq import GroqWhisper


class MockResponse:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def test_whisper_transcribe_returns_text(ai_config, monkeypatch):
    mock_body = '{"text":"你好嗎"}'

    def mock_urlopen(req, timeout=None):
        return MockResponse(mock_body.encode())

    monkeypatch.setenv("WA_GROQ_API_KEY", "test-groq-key")

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        whisper = GroqWhisper(ai_config)
        result = whisper.transcribe(b"fake audio data")
        assert result == "你好嗎"


def test_whisper_transcribe_returns_none_without_api_key(ai_config, monkeypatch):
    monkeypatch.setenv("WA_GROQ_API_KEY", "")
    whisper = GroqWhisper(ai_config)
    assert whisper.transcribe(b"fake audio") is None


def test_whisper_transcribe_returns_none_on_api_error(ai_config, monkeypatch):
    def mock_urlopen(req, timeout=None):
        raise Exception("API error")

    monkeypatch.setenv("WA_GROQ_API_KEY", "test-key")

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        whisper = GroqWhisper(ai_config)
        assert whisper.transcribe(b"fake audio") is None


def test_whisper_transcribe_returns_none_on_empty_response(ai_config, monkeypatch):
    mock_body = '{"text":""}'

    def mock_urlopen(req, timeout=None):
        return MockResponse(mock_body.encode())

    monkeypatch.setenv("WA_GROQ_API_KEY", "test-key")

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        whisper = GroqWhisper(ai_config)
        assert whisper.transcribe(b"fake audio") is None


def test_whisper_transcribe_sends_language(ai_config, monkeypatch):
    mock_body = '{"text":"test"}'

    captured_req = []

    def mock_urlopen(req, timeout=None):
        captured_req.append(req)
        return MockResponse(mock_body.encode())

    monkeypatch.setenv("WA_GROQ_API_KEY", "test-key")

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        whisper = GroqWhisper(ai_config)
        whisper.transcribe(b"fake audio", language="yue")
        assert len(captured_req) == 1
        assert b"yue" in captured_req[0].data
