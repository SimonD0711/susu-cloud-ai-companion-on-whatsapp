"""Tests for src.ai.llm.manager."""

import pytest
from unittest.mock import patch, MagicMock

from src.ai.base import LLMMessage
from src.ai.llm.manager import LLMManager


class MockResponse:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def test_llm_manager_chat_returns_response(ai_config):
    mock_body = b'{"choices":[{"message":{"content":"test reply"}}]}'

    def mock_urlopen(req, timeout=None):
        return MockResponse(mock_body)

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        manager = LLMManager(ai_config)
        resp = manager.chat([LLMMessage(role="user", content="hello")])
        assert resp.content == "test reply"


def test_llm_manager_chat_text(ai_config):
    mock_body = b'{"choices":[{"message":{"content":"ok reply"}}]}'

    def mock_urlopen(req, timeout=None):
        return MockResponse(mock_body)

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        manager = LLMManager(ai_config)
        text = manager.chat_text([LLMMessage(role="user", content="hi")])
        assert text == "ok reply"


def test_llm_manager_unknown_provider_raises(ai_config):
    manager = LLMManager(ai_config)
    with pytest.raises(ValueError, match="Unknown provider"):
        manager.chat([LLMMessage(role="user", content="hi")], provider="unknown")


def test_llm_manager_uses_config_defaults(ai_config):
    mock_body = b'{"choices":[{"message":{"content":"ok"}}]}'

    captured_req = []

    def mock_urlopen(req, timeout=None):
        captured_req.append(req)
        return MockResponse(mock_body)

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        manager = LLMManager(ai_config)
        manager.chat([LLMMessage(role="user", content="test")])
        assert len(captured_req) == 1
        assert "claude-opus-4-6" in captured_req[0].data.decode()
