"""Tests for src.wa_agent.memory."""

import importlib.util
import sqlite3
from pathlib import Path

import pytest

from src.wa_agent.memory import (
    is_long_term_memory_candidate,
    is_recent_memory_candidate,
    normalize_key,
    normalize_recent_bucket,
    classify_recent_memory_bucket,
    infer_observed_at_from_text,
    MemoryManager,
    MEMORY_EXTRACTOR_PROMPT,
    RECENT_MEMORY_EXTRACTOR_PROMPT,
)


def test_is_long_term_memory_candidate_valid():
    assert is_long_term_memory_candidate("Simon喺香港讀書") is True
    assert is_long_term_memory_candidate("我最鍾意周杰倫") is True


def test_is_long_term_memory_candidate_too_short():
    assert is_long_term_memory_candidate("你好") is False
    assert is_long_term_memory_candidate("hi") is False


def test_is_long_term_memory_candidate_greetings():
    assert is_long_term_memory_candidate("早晨") is False
    assert is_long_term_memory_candidate("晚安") is False
    assert is_long_term_memory_candidate("Thank you") is False


def test_is_long_term_memory_candidate_too_long():
    assert is_long_term_memory_candidate("A" * 300) is False


def test_is_recent_memory_candidate_valid():
    assert is_recent_memory_candidate("今日約咗朋友") is True
    assert is_recent_memory_candidate("聽日考試") is True


def test_is_recent_memory_candidate_too_short():
    assert is_recent_memory_candidate("好") is False
    assert is_recent_memory_candidate("X") is False


def test_normalize_key():
    key = normalize_key("Simon 最鍾意周杰倫！?")
    assert len(key) <= 160
    assert key.islower() or not any(c.isalpha() for c in key)


def test_normalize_key_strips_chinese_punctuation():
    key1 = normalize_key("今日約咗朋友。")
    key2 = normalize_key("今日約咗朋友")
    assert key1 == key2


def test_infer_observed_at_past_markers():
    from datetime import datetime, timezone
    now = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    result = infer_observed_at_from_text("尋晚睇咗個片", now)
    assert result is not None
    assert result.day == 2


def test_infer_observed_at_future_markers():
    from datetime import datetime, timezone
    now = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    result = infer_observed_at_from_text("聽日考試", now)
    assert result is not None
    assert result.day == 4


def test_infer_observed_at_no_marker():
    from datetime import datetime, timezone
    now = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    result = infer_observed_at_from_text("我鍾意周杰倫", now)
    assert result is None


def test_infer_observed_at_within_24h():
    from datetime import datetime, timezone
    now = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    result = infer_observed_at_from_text("啱啱上完堂", now)
    assert result is not None
    assert result.day == 3


def test_classify_recent_memory_bucket_all_markers():
    assert classify_recent_memory_bucket("今晚去睇戲") == "within_24h"
    assert classify_recent_memory_bucket("尋晚睇咗個片") == "within_3d"
    assert classify_recent_memory_bucket("最近忙緊") == "within_7d"
    assert classify_recent_memory_bucket("昨日考試") == "within_3d"
    assert classify_recent_memory_bucket("聽日上堂") == "within_3d"
    assert classify_recent_memory_bucket("呢兩三日感冒") == "within_3d"


def test_normalize_recent_bucket_within_24h():
    assert normalize_recent_bucket("within_24h") == "within_24h"
    assert normalize_recent_bucket("today") == "within_24h"
    assert normalize_recent_bucket("tonight") == "within_24h"


def test_normalize_recent_bucket_within_3d():
    assert normalize_recent_bucket("within_3d") == "within_3d"
    assert normalize_recent_bucket("") == "within_7d"


def test_normalize_recent_bucket_within_7d():
    assert normalize_recent_bucket("within_7d") == "within_7d"
    assert normalize_recent_bucket("unknown") == "within_7d"


def test_classify_recent_memory_bucket_24h():
    assert classify_recent_memory_bucket("今日約咗朋友") == "within_24h"
    assert classify_recent_memory_bucket("今晚去睇戲") == "within_24h"


def test_classify_recent_memory_bucket_3d():
    assert classify_recent_memory_bucket("尋晚睇咗個片") == "within_3d"
    assert classify_recent_memory_bucket("聽日考試") == "within_3d"


def test_classify_recent_memory_bucket_7d():
    assert classify_recent_memory_bucket("呢個星期要交功課") == "within_7d"
    assert classify_recent_memory_bucket("普通句子") == "within_7d"


def test_memory_extractor_prompt_not_empty():
    assert MEMORY_EXTRACTOR_PROMPT
    assert len(MEMORY_EXTRACTOR_PROMPT) > 50


def test_recent_memory_extractor_prompt_not_empty():
    assert RECENT_MEMORY_EXTRACTOR_PROMPT
    assert len(RECENT_MEMORY_EXTRACTOR_PROMPT) > 50


def test_memory_manager_has_extract_methods():
    from src.wa_agent.memory import MemoryManager
    assert hasattr(MemoryManager, "extract_and_save_long_term")
    assert hasattr(MemoryManager, "extract_and_save_session")
    assert hasattr(MemoryManager, "is_long_term_candidate")
    assert hasattr(MemoryManager, "is_recent_candidate")
    assert hasattr(MemoryManager, "normalize_key")
    assert hasattr(MemoryManager, "normalize_bucket")
    assert hasattr(MemoryManager, "classify_bucket")
    assert hasattr(MemoryManager, "infer_observed_at")


def _load_root_wa_agent_module():
    module_path = Path(__file__).resolve().parents[2] / "wa_agent.py"
    spec = importlib.util.spec_from_file_location("root_wa_agent", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_should_trigger_session_extraction_uses_five_rounds(monkeypatch):
    wa_agent = _load_root_wa_agent_module()

    wa_agent._session_extraction_state.clear()
    monkeypatch.setattr(wa_agent.time, "time", lambda: 1000.0)

    results = [wa_agent._should_trigger_session_extraction("85260000000") for _ in range(5)]

    assert results == [False, False, False, False, False]
    assert wa_agent._should_trigger_session_extraction("85260000000") is True


def test_should_trigger_session_extraction_uses_thirty_minutes(monkeypatch):
    wa_agent = _load_root_wa_agent_module()

    wa_agent._session_extraction_state.clear()
    wa_agent._session_extraction_state["85260000000"] = {"turns": 1, "last_at": 1000.0}
    monkeypatch.setattr(wa_agent.time, "time", lambda: 2801.0)

    assert wa_agent._should_trigger_session_extraction("85260000000") is True


def test_maybe_extract_session_memories_fallback_writes_daily_log(monkeypatch):
    wa_agent = _load_root_wa_agent_module()
    from src.wa_agent.db import MemoryDB

    db = MemoryDB(":memory:")
    conn = db.init_db()
    conn.row_factory = sqlite3.Row

    monkeypatch.setattr(wa_agent, "generate_model_text", lambda *args, **kwargs: "[]")
    monkeypatch.setattr(
        wa_agent,
        "heuristic_extract_session_memories",
        lambda text: [{"content": "尋晚去咗睇戲", "observed_at": None}],
    )
    monkeypatch.setattr(wa_agent, "promote_to_long_term", lambda *args, **kwargs: None)
    monkeypatch.setattr(wa_agent, "hk_today", lambda: wa_agent.datetime(2026, 4, 3, tzinfo=wa_agent.HK_TZ).date())
    monkeypatch.setattr(wa_agent, "hk_now", lambda: wa_agent.datetime.fromisoformat("2026-04-03T12:34:00+08:00"))

    saved = wa_agent.maybe_extract_session_memories(conn, "85260000000", "尋晚去咗睇戲")
    row = conn.execute(
        "SELECT bucket, memory_key, content FROM wa_session_memories WHERE wa_id = ?",
        ("85260000000",),
    ).fetchone()

    assert saved == ["尋晚去咗睇戲"]
    assert row is not None
    assert row["bucket"] == "daily_log"
    assert row["memory_key"] == "daily:2026-04-02"
    assert "12:34 尋晚去咗睇戲" in row["content"]


def test_daily_log_backfill_target_date_runs_once_per_day():
    wa_agent = _load_root_wa_agent_module()

    now = wa_agent.datetime.fromisoformat("2026-04-05T03:59:10+08:00")
    assert wa_agent.daily_log_backfill_target_date(now) == "2026-04-04"

    wa_agent._daily_log_backfill_state["last_target_date"] = "2026-04-04"
    assert wa_agent.run_daily_log_backfill_once(now)["status"] == "already_ran"


def test_backfill_daily_log_for_date_when_logs_are_sparse(monkeypatch):
    wa_agent = _load_root_wa_agent_module()
    from src.wa_agent.db import MemoryDB

    db = MemoryDB(":memory:")
    conn = db.init_db()
    conn.row_factory = sqlite3.Row
    wa_id = "85260000000"

    rows = [
        (wa_id, "inbound", "m1", "text", "今日返學好攰", "{}", "2026-04-04T09:00:00+08:00"),
        (wa_id, "outbound", "m2", "text", "你仲頂得順嗎", "{}", "2026-04-04T09:01:00+08:00"),
        (wa_id, "inbound", "m3", "text", "啱啱上完堂", "{}", "2026-04-04T11:00:00+08:00"),
        (wa_id, "inbound", "m4", "text", "今晚要趕project", "{}", "2026-04-04T14:00:00+08:00"),
        (wa_id, "inbound", "m5", "text", "可能要通頂", "{}", "2026-04-04T18:00:00+08:00"),
        (wa_id, "inbound", "m6", "text", "啱啱食完飯返到宿舍", "{}", "2026-04-04T21:00:00+08:00"),
        (wa_id, "inbound", "m7", "text", "聽日朝早仲要開會", "{}", "2026-04-05T01:00:00+08:00"),
    ]
    conn.executemany(
        "INSERT INTO wa_messages (wa_id, direction, message_id, message_type, body, raw_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    wa_agent.upsert_daily_log(conn, wa_id, "2026-04-04", "今日返學好攰", logged_at="09:05")
    conn.commit()

    monkeypatch.setattr(
        wa_agent,
        "generate_model_text",
        lambda *args, **kwargs: '[{"content":"今晚要趕project","observed_at":"2026-04-04"},{"content":"啱啱食完飯返到宿舍","observed_at":"2026-04-04"}]',
    )
    monkeypatch.setattr(wa_agent, "promote_to_long_term", lambda *args, **kwargs: None)
    monkeypatch.setattr(wa_agent, "hk_now", lambda: wa_agent.datetime.fromisoformat("2026-04-05T03:59:00+08:00"))

    result = wa_agent.backfill_daily_log_for_date(conn, wa_id, "2026-04-04")
    row = conn.execute(
        "SELECT content FROM wa_session_memories WHERE wa_id = ? AND memory_key = ?",
        (wa_id, "daily:2026-04-04"),
    ).fetchone()

    assert result["reason"] == "backfilled"
    assert result["saved"] == ["今晚要趕project", "啱啱食完飯返到宿舍"]
    assert row is not None
    assert "09:05 今日返學好攰" in row["content"]
    assert "03:59 今晚要趕project" in row["content"]
    assert "03:59 啱啱食完飯返到宿舍" in row["content"]
