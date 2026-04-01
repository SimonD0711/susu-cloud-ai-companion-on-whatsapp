"""Tests for src.wa_agent.brain."""

import pytest
from datetime import datetime, timezone

from src.wa_agent.brain import (
    normalize_reply,
    shorten_whatsapp_reply,
    looks_fragmentary,
    contains_sleep_nag,
    is_night_mode,
    get_time_profile,
    ReplyBrain,
)


def test_normalize_reply_empty():
    assert normalize_reply("") == ""
    assert normalize_reply(None) == ""
    assert normalize_reply("   ") == ""


def test_normalize_reply_basic():
    assert normalize_reply("  hello  ") == "hello"
    assert normalize_reply("hello\r\nworld") == "hello\n\nworld"


def test_normalize_reply_trims_quotes():
    assert normalize_reply('"hello"') == "hello"
    assert normalize_reply("'hello'") == "hello"
    assert normalize_reply(" `hello` ") == "hello"


def test_shorten_whatsapp_reply_empty():
    assert shorten_whatsapp_reply("") == ""
    assert shorten_whatsapp_reply("   ") == ""


def test_shorten_whatsapp_reply_basic():
    assert shorten_whatsapp_reply("Hello") == "Hello"


def test_shorten_whatsapp_reply_is_normalize():
    result = shorten_whatsapp_reply("  hello world  ")
    assert result == "hello world"


def test_looks_fragmentary_empty():
    assert looks_fragmentary("", "hello") is True
    assert looks_fragmentary(None, "hello") is True


def test_looks_fragmentary_too_short():
    assert looks_fragmentary("ABC", "hello") is True


def test_looks_fragmentary_starts_with_conjunction():
    assert looks_fragmentary("因為", "hello") is True
    assert looks_fragmentary("所以天氣不錯", "hello") is True


def test_looks_fragmentary_trailing_punctuation():
    assert looks_fragmentary("這是回覆,", "question") is True
    assert looks_fragmentary("早安你好", "question") is True


def test_looks_fragmentary_ok():
    assert looks_fragmentary("這是一個完整的回覆。", "question") is False


def test_contains_sleep_nag_positive():
    assert contains_sleep_nag("早啲訓啦") is True
    assert contains_sleep_nag("去睡啦你") is True
    assert contains_sleep_nag("夜晚唔好催我瞓") is True


def test_contains_sleep_nag_negative():
    assert contains_sleep_nag("早晨") is False
    assert contains_sleep_nag("今日天氣好") is False


def test_is_night_mode_evening():
    dt = datetime(2026, 4, 1, 23, 0, tzinfo=timezone.utc)
    assert is_night_mode(dt) is True


def test_is_night_mode_midnight():
    dt = datetime(2026, 4, 1, 0, 30, tzinfo=timezone.utc)
    assert is_night_mode(dt) is True


def test_is_night_mode_afternoon():
    dt = datetime(2026, 4, 1, 15, 0, tzinfo=timezone.utc)
    assert is_night_mode(dt) is False


def test_get_time_profile_morning():
    dt = datetime(2026, 4, 1, 8, 0, tzinfo=timezone.utc)
    assert get_time_profile(dt) == "morning"


def test_get_time_profile_busy_day():
    dt = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)
    assert get_time_profile(dt) == "busy_day"


def test_get_time_profile_evening():
    dt = datetime(2026, 4, 1, 19, 0, tzinfo=timezone.utc)
    assert get_time_profile(dt) == "evening"


def test_get_time_profile_late_night():
    dt = datetime(2026, 4, 1, 23, 0, tzinfo=timezone.utc)
    assert get_time_profile(dt) == "late_night"


def test_reply_brain_has_generate_method():
    from src.ai.config import AIConfig
    from src.wa_agent.brain import ReplyBrain
    config = AIConfig()
    brain = ReplyBrain(config)
    assert hasattr(brain, "generate")
    assert callable(brain.generate)
