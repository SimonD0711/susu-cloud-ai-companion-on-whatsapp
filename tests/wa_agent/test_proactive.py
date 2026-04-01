"""Tests for src.wa_agent.proactive."""

import pytest
from datetime import datetime, timezone
from src.wa_agent.proactive import (
    _sigmoid,
    _is_night_mode,
    _get_time_profile,
    proactive_slot_key,
    proactive_slot_hint,
    style_window_text,
    _clean_text,
    _normalize_key,
    _normalize_bucket,
    split_profile_memory_lines,
    memories_look_duplicated,
    build_core_profile_memory_text,
    build_filtered_long_term_memory_lines,
    normalize_recent_bucket,
    recent_bucket_label,
    current_recent_bucket,
    format_memory_timestamp,
)


def test_sigmoid():
    assert 0.5 == _sigmoid(0)
    assert 1.0 == _sigmoid(100)
    assert _sigmoid(-100) < 1e-10


def test_is_night_mode_evening():
    dt = datetime(2026, 4, 1, 23, 0, tzinfo=timezone.utc)
    assert _is_night_mode(dt) is True


def test_is_night_mode_midnight():
    dt = datetime(2026, 4, 1, 0, 30, tzinfo=timezone.utc)
    assert _is_night_mode(dt) is True


def test_is_night_mode_afternoon():
    dt = datetime(2026, 4, 1, 15, 0, tzinfo=timezone.utc)
    assert _is_night_mode(dt) is False


def test_get_time_profile_morning():
    dt = datetime(2026, 4, 1, 8, 0, tzinfo=timezone.utc)
    assert _get_time_profile(dt) == "morning"


def test_get_time_profile_busy_day():
    dt = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)
    assert _get_time_profile(dt) == "busy_day"


def test_get_time_profile_evening():
    dt = datetime(2026, 4, 1, 19, 0, tzinfo=timezone.utc)
    assert _get_time_profile(dt) == "evening"


def test_get_time_profile_late_night():
    dt = datetime(2026, 4, 1, 23, 0, tzinfo=timezone.utc)
    assert _get_time_profile(dt) == "late_night"


def test_proactive_slot_key_morning():
    dt = datetime(2026, 4, 1, 8, 0, tzinfo=timezone.utc)
    assert proactive_slot_key(dt) == "morning"


def test_proactive_slot_key_afternoon():
    dt = datetime(2026, 4, 1, 14, 0, tzinfo=timezone.utc)
    assert proactive_slot_key(dt) == "afternoon"


def test_proactive_slot_key_evening():
    dt = datetime(2026, 4, 1, 19, 0, tzinfo=timezone.utc)
    assert proactive_slot_key(dt) == "evening"


def test_proactive_slot_key_late_night():
    dt = datetime(2026, 4, 1, 23, 0, tzinfo=timezone.utc)
    assert proactive_slot_key(dt) == "late_night"


def test_proactive_slot_hint_returns_string():
    dt = datetime(2026, 4, 1, 8, 0, tzinfo=timezone.utc)
    hint = proactive_slot_hint(dt)
    assert isinstance(hint, str)
    assert len(hint) > 0


def test_style_window_text_returns_string():
    dt = datetime(2026, 4, 1, 8, 0, tzinfo=timezone.utc)
    text = style_window_text(dt)
    assert isinstance(text, str)
    assert len(text) > 0


def test_clean_text():
    assert _clean_text("  hello  world  ") == "hello world"
    assert _clean_text(None) == ""
    assert _clean_text("") == ""


def test_normalize_key():
    assert _normalize_key("Hello World") == "helloworld"
    assert _normalize_key("你好") == "你好"
    assert _normalize_key("") == ""


def test_normalize_bucket():
    assert _normalize_bucket("within_24h") == "within_24h"
    assert _normalize_bucket("within_day") == "within_24h"
    assert _normalize_bucket("day") == "within_24h"
    assert _normalize_bucket("within_30d") == "within_30d"
    assert _normalize_bucket("") == "within_7d"
    assert _normalize_bucket("unknown") == "within_7d"


def test_split_profile_memory_lines():
    lines = split_profile_memory_lines("- 喜歡食火鍋\n- 鍾意去旅行\n  - 不喜歡早起")
    assert len(lines) == 3


def test_memories_look_duplicated_exact():
    assert memories_look_duplicated("喜歡食火鍋", "喜歡食火鍋") is True


def test_memories_look_duplicated_substring():
    long_text = "this_is_a_long_memory"
    short_text = "this_is_a_long"
    assert memories_look_duplicated(short_text, long_text) is True


def test_memories_look_duplicated_different():
    assert memories_look_duplicated("喜歡食火鍋", "鍾意去旅行") is False


def test_build_core_profile_memory_text():
    text = "- 喜歡食火鍋\n- 鍾意去旅行\n- 早起"
    result = build_core_profile_memory_text(text)
    assert isinstance(result, str)
    assert len(result) > 0


def test_build_filtered_long_term_memory_lines():
    rows = [
        {"content": "喜歡食火鍋"},
        {"content": "鍾意去旅行"},
    ]
    result = build_filtered_long_term_memory_lines(rows, "")
    assert len(result) == 2


def test_normalize_recent_bucket_within_24h():
    assert normalize_recent_bucket("within_24h") == "within_24h"
    assert normalize_recent_bucket("today") == "within_24h"
    assert normalize_recent_bucket("tonight") == "within_24h"


def test_normalize_recent_bucket_within_3d():
    assert normalize_recent_bucket("within_3d") == "within_3d"
    assert normalize_recent_bucket("last_night") == "within_3d"


def test_normalize_recent_bucket_within_7d():
    assert normalize_recent_bucket("within_7d") == "within_7d"
    assert normalize_recent_bucket("recent_days") == "within_7d"
    assert normalize_recent_bucket("unknown") == "within_7d"


def test_recent_bucket_label():
    assert recent_bucket_label("within_24h") == "24小時內"
    assert recent_bucket_label("within_3d") == "三天內"
    assert recent_bucket_label("within_7d") == "一週內"
    assert recent_bucket_label("unknown") == "一週內"


def test_current_recent_bucket():
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    assert current_recent_bucket((now - timedelta(hours=2)).isoformat()) == "within_24h"
    assert current_recent_bucket((now - timedelta(hours=48)).isoformat()) == "within_3d"
    assert current_recent_bucket((now - timedelta(days=5)).isoformat()) == "within_7d"
    assert current_recent_bucket("") == "within_7d"


def test_format_memory_timestamp():
    ts = "2026-04-01T10:30:00+08:00"
    result = format_memory_timestamp(ts)
    assert isinstance(result, str)
    assert "04-01" in result or "10:30" in result
