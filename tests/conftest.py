"""pytest global configuration and fixtures."""

import pytest


@pytest.fixture(autouse=True)
def default_env(monkeypatch):
    monkeypatch.setenv("WA_RELAY_API_KEY", "test-relay-api-key")
    monkeypatch.setenv("WA_RELAY_MODEL", "claude-opus-4-6")
    monkeypatch.setenv("WA_RELAY_FALLBACK_MODEL", "claude-sonnet-4-6")
    monkeypatch.setenv("WA_RELAY_BASE_URL", "https://apiapipp.com/v1")
    monkeypatch.setenv("WA_RELAY_RETRY_COUNT", "2")
    monkeypatch.setenv("WA_RELAY_RETRY_BACKOFF_SECONDS", "1.0")
    monkeypatch.setenv("WA_MINIMAX_API_KEY", "test-minimax-api-key")
    monkeypatch.setenv("WA_MINIMAX_BASE_URL", "https://api.minimaxaxi.com/v1")
    monkeypatch.setenv("WA_TTS_VOICE_ID", "Cantonese_CuteGirl")
    monkeypatch.setenv("WA_GROQ_API_KEY", "test-groq-api-key")
    monkeypatch.setenv("WA_ADMIN_WA_ID", "85259576670")
    monkeypatch.setenv("SUSU_BASE_DIR", "/tmp/susu-test")
    monkeypatch.setenv("SUSU_ADMIN_PASSWORD_SALT_B64", "dGVzdHNhbHQ=")
    monkeypatch.setenv("SUSU_ADMIN_PASSWORD_HASH_B64", "dGVzdGhhc2g=")


@pytest.fixture
def ai_config():
    from src.ai.config import AIConfig
    return AIConfig()


@pytest.fixture
def llm_manager(ai_config):
    from src.ai.llm.manager import LLMManager
    return LLMManager(ai_config)
