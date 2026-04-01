"""Centralized AI configuration — single source of truth for all AI-related env vars."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(key: str, default: str = "", required: bool = False) -> str:
    value = os.environ.get(key, default)
    if required and not value:
        raise KeyError(f"Required environment variable {key} is not set")
    return value


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, str(default)))
    except (ValueError, TypeError):
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, str(default)))
    except (ValueError, TypeError):
        return default


def _env_bool(key: str, default: bool) -> bool:
    val = os.environ.get(key, "")
    if val.lower() in ("1", "true", "yes", "on"):
        return True
    if val.lower() in ("0", "false", "no", "off"):
        return False
    return default


@dataclass
class AIConfig:
    """All AI-related configuration. Use this instead of scattered os.environ calls."""

    # ─── LLM (Relay) ───────────────────────────────────────────────
    RELAY_API_KEY: str = field(default_factory=lambda: _env("WA_RELAY_API_KEY", required=True))
    RELAY_MODEL: str = field(default_factory=lambda: _env("WA_RELAY_MODEL", "claude-opus-4-6"))
    RELAY_FALLBACK_MODEL: str = field(default_factory=lambda: _env("WA_RELAY_FALLBACK_MODEL", "claude-sonnet-4-6"))
    RELAY_BASE_URL: str = field(default_factory=lambda: _env("WA_RELAY_BASE_URL", "https://apiapipp.com/v1"))
    RELAY_RETRY_COUNT: int = field(default_factory=lambda: _env_int("WA_RELAY_RETRY_COUNT", 2))
    RELAY_RETRY_BACKOFF_SECONDS: float = field(default_factory=lambda: _env_float("WA_RELAY_RETRY_BACKOFF_SECONDS", 1.0))

    # ─── Gemini (defined but currently unused) ───────────────────────
    GEMINI_API_KEY: str = field(default_factory=lambda: _env("WA_GEMINI_API_KEY") or _env("GOOGLE_KEY", ""))
    GEMINI_MODEL: str = field(default_factory=lambda: _env("WA_GEMINI_MODEL", "gemini-2.5-flash"))

    # ─── MiniMax TTS ───────────────────────────────────────────────
    MINIMAX_API_KEY: str = field(default_factory=lambda: _env("WA_MINIMAX_API_KEY", required=True))
    MINIMAX_BASE_URL: str = field(default_factory=lambda: _env("WA_MINIMAX_BASE_URL", "https://api.minimaxaxi.com/v1"))
    TTS_VOICE_ID: str = field(default_factory=lambda: _env("WA_TTS_VOICE_ID", "Cantonese_CuteGirl"))
    TTS_SPEED: float = field(default_factory=lambda: _env_float("WA_TTS_SPEED", 1.0))

    # ─── Whisper (Groq) ─────────────────────────────────────────────
    GROQ_API_KEY: str = field(
        default_factory=lambda: _env("WA_GROQ_API_KEY") or _env("GROQ_API_KEY", "")
    )

    # ─── Search / Live Data ─────────────────────────────────────────
    TAVILY_API_KEY: str = field(default_factory=lambda: _env("WA_TAVILY_API_KEY", ""))
    BING_API_KEY: str = field(default_factory=lambda: _env("WA_BING_API_KEY", ""))
    YOUTUBE_API_KEY: str = field(default_factory=lambda: _env("WA_YOUTUBE_API_KEY", ""))
    X_BEARER_TOKEN: str = field(default_factory=lambda: _env("WA_X_BEARER_TOKEN", ""))
    REDDIT_USER_AGENT: str = field(default_factory=lambda: _env("WA_REDDIT_USER_AGENT", "SusuCloud/1.0"))
    OPENWEATHER_API_KEY: str = field(default_factory=lambda: _env("WA_OPENWEATHER_API_KEY", ""))
    SPOTIFY_CLIENT_ID: str = field(default_factory=lambda: _env("WA_SPOTIFY_CLIENT_ID", ""))
    SPOTIFY_CLIENT_SECRET: str = field(default_factory=lambda: _env("WA_SPOTIFY_CLIENT_SECRET", ""))

    # ─── Proactive Messaging ─────────────────────────────────────────
    PROACTIVE_ENABLED: bool = field(default_factory=lambda: _env_bool("WA_PROACTIVE_ENABLED", True))
    PROACTIVE_SCAN_SECONDS: int = field(default_factory=lambda: _env_int("WA_PROACTIVE_SCAN_SECONDS", 300))
    PROACTIVE_MIN_SILENCE_MINUTES: int = field(default_factory=lambda: _env_int("WA_PROACTIVE_MIN_SILENCE_MINUTES", 45))
    PROACTIVE_COOLDOWN_MINUTES: int = field(default_factory=lambda: _env_int("WA_PROACTIVE_COOLDOWN_MINUTES", 180))
    PROACTIVE_REPLY_WINDOW_MINUTES: int = field(default_factory=lambda: _env_int("WA_PROACTIVE_REPLY_WINDOW_MINUTES", 90))
    PROACTIVE_CONVERSATION_WINDOW_HOURS: int = field(default_factory=lambda: _env_int("WA_PROACTIVE_CONVERSATION_WINDOW_HOURS", 24))
    PROACTIVE_MAX_PER_SERVICE_DAY: int = field(default_factory=lambda: _env_int("WA_PROACTIVE_MAX_PER_SERVICE_DAY", 2))
    PROACTIVE_MIN_INBOUND_MESSAGES: int = field(default_factory=lambda: _env_int("WA_PROACTIVE_MIN_INBOUND_MESSAGES", 8))

    # ─── WhatsApp ───────────────────────────────────────────────────
    ADMIN_WA_ID: str = field(default_factory=lambda: _env("WA_ADMIN_WA_ID", "85259576670"))
    MAX_IMAGE_ATTACHMENTS: int = field(default_factory=lambda: _env_int("WA_MAX_IMAGE_ATTACHMENTS", 3))
    MAX_IMAGE_BYTES: int = field(default_factory=lambda: _env_int("WA_MAX_IMAGE_BYTES", 5 * 1024 * 1024))

    def reload(self) -> "AIConfig":
        """Re-read all environment variables and return a new AIConfig."""
        return AIConfig()
