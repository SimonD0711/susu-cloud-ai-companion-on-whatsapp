"""Tests for src.ai.tts.minimax."""

import pytest
from unittest.mock import patch, MagicMock

from src.ai.tts.minimax import MiniMaxTTS


class MockResponse:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def test_tts_speak_returns_path_on_success(ai_config, monkeypatch):
    mock_body = '{"data":{"audio":"48656c6c6f"}}'

    def mock_urlopen(req, timeout=None):
        return MockResponse(mock_body.encode())

    monkeypatch.setenv("WA_MINIMAX_API_KEY", "test-minimax-key")
    monkeypatch.setenv("WA_MINIMAX_BASE_URL", "https://api.minimax.com/v1")
    monkeypatch.setenv("WA_TTS_VOICE_ID", "Cantonese_CuteGirl")

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        tts = MiniMaxTTS(ai_config)
        result = tts.speak("Hello", output_path="/tmp/test_voice.mp3")
        assert result == "/tmp/test_voice.mp3"


def test_tts_speak_returns_none_on_empty_text(ai_config):
    tts = MiniMaxTTS(ai_config)
    assert tts.speak("") is None
    assert tts.speak(None) is None


def test_tts_speak_returns_none_without_api_key(ai_config, monkeypatch):
    monkeypatch.setenv("WA_MINIMAX_API_KEY", "")
    tts = MiniMaxTTS(ai_config)
    assert tts.speak("Hello") is None


def test_tts_speak_returns_none_on_api_error(ai_config, monkeypatch):
    def mock_urlopen(req, timeout=None):
        raise Exception("API error")

    monkeypatch.setenv("WA_MINIMAX_API_KEY", "test-key")

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        tts = MiniMaxTTS(ai_config)
        assert tts.speak("Hello") is None


def test_tts_speak_uses_config_defaults(ai_config, monkeypatch):
    mock_body = '{"data":{"audio":"48656c6c6f"}}'

    captured_req = []

    def mock_urlopen(req, timeout=None):
        captured_req.append(req)
        return MockResponse(mock_body.encode())

    monkeypatch.setenv("WA_MINIMAX_API_KEY", "test-key")
    monkeypatch.setenv("WA_MINIMAX_BASE_URL", "https://api.minimax.com/v1")
    monkeypatch.setenv("WA_TTS_VOICE_ID", "Cantonese_CuteGirl")

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        tts = MiniMaxTTS(ai_config)
        tts.speak("Hello")
        assert len(captured_req) == 1
        assert "Cantonese_CuteGirl" in captured_req[0].data.decode()
