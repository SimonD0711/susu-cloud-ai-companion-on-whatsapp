"""Tests for src.ai.config."""

import importlib
import pytest


def test_config_reads_relay_env(monkeypatch):
    monkeypatch.setenv("WA_RELAY_API_KEY", "my-test-key")
    monkeypatch.setenv("WA_RELAY_MODEL", "claude-opus-4-6")
    monkeypatch.setenv("WA_RELAY_BASE_URL", "https://api.example.com/v1")
    import src.ai.config
    importlib.reload(src.ai.config)
    from src.ai.config import AIConfig
    cfg = AIConfig()
    assert cfg.RELAY_API_KEY == "my-test-key"
    assert cfg.RELAY_MODEL == "claude-opus-4-6"
    assert cfg.RELAY_BASE_URL == "https://api.example.com/v1"


def test_config_defaults(monkeypatch):
    monkeypatch.delenv("WA_RELAY_MODEL", raising=False)
    monkeypatch.delenv("WA_RELAY_RETRY_COUNT", raising=False)
    import src.ai.config
    importlib.reload(src.ai.config)
    from src.ai.config import AIConfig
    cfg = AIConfig()
    assert cfg.RELAY_MODEL == "claude-opus-4-6"
    assert cfg.RELAY_RETRY_COUNT == 2
    assert cfg.RELAY_RETRY_BACKOFF_SECONDS == 1.0


def test_config_tts_defaults():
    from src.ai.config import AIConfig
    cfg = AIConfig()
    assert cfg.TTS_VOICE_ID == "Cantonese_CuteGirl"
    assert cfg.TTS_SPEED == 1.0


def test_config_groq_fallback(monkeypatch):
    monkeypatch.delenv("WA_GROQ_API_KEY", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "groq-from-fallback")
    import src.ai.config
    importlib.reload(src.ai.config)
    from src.ai.config import AIConfig
    cfg = AIConfig()
    assert cfg.GROQ_API_KEY == "groq-from-fallback"


def test_config_proactive_defaults():
    from src.ai.config import AIConfig
    cfg = AIConfig()
    assert cfg.PROACTIVE_ENABLED is True
    assert cfg.PROACTIVE_SCAN_SECONDS == 300
    assert cfg.PROACTIVE_MIN_SILENCE_MINUTES == 45


def test_config_int_helper(monkeypatch):
    monkeypatch.setenv("WA_PROACTIVE_SCAN_SECONDS", "600")
    import src.ai.config
    importlib.reload(src.ai.config)
    from src.ai.config import AIConfig
    cfg = AIConfig()
    assert cfg.PROACTIVE_SCAN_SECONDS == 600


def test_config_bool_helper(monkeypatch):
    monkeypatch.setenv("WA_PROACTIVE_ENABLED", "0")
    import src.ai.config
    importlib.reload(src.ai.config)
    from src.ai.config import AIConfig
    cfg = AIConfig()
    assert cfg.PROACTIVE_ENABLED is False
