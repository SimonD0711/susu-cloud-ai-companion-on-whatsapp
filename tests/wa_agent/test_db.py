"""Tests for src.wa_agent.db."""

import pytest
import sqlite3
import tempfile
import os
from pathlib import Path

from src.wa_agent.db import MemoryDB


@pytest.fixture
def mem_db():
    """Create an in-memory MemoryDB for testing."""
    db = MemoryDB(":memory:")
    db.init_db()
    yield db
    db.close()


@pytest.fixture
def file_db():
    """Create a file-based MemoryDB with a temp file."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    db = MemoryDB(db_path)
    db.init_db()
    yield db
    db.close()
    try:
        os.unlink(db_path)
    except Exception:
        pass


def test_memory_db_init(mem_db):
    conn = mem_db.connect()
    assert conn is not None
    assert conn.row_factory == sqlite3.Row


def test_memory_db_create_tables(mem_db):
    tables = ["wa_messages", "wa_contacts", "wa_memories", "wa_image_stats",
              "wa_session_memories", "wa_memory_archive", "wa_proactive_events",
              "wa_proactive_slot_stats", "wa_claude_mode", "wa_reminders"]
    for table in tables:
        result = mem_db.execute(
            f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'"
        ).fetchone()
        assert result is not None, f"Table {table} not created"


def test_upsert_memory(mem_db):
    result = mem_db.upsert_memory("85260000000", "Simon likes coffee", kind="fact", importance=4)
    assert result is True
    memories = mem_db.load_memories("85260000000")
    assert len(memories) == 1
    assert memories[0]["content"] == "Simon likes coffee"
    assert memories[0]["kind"] == "fact"
    assert memories[0]["importance"] == 4


def test_upsert_memory_idempotent(mem_db):
    mem_db.upsert_memory("85260000000", "Same fact", kind="note", importance=3)
    mem_db.upsert_memory("85260000000", "Same fact", kind="note", importance=5)
    mem_db.commit()
    memories = mem_db.load_memories("85260000000")
    assert len(memories) == 1
    assert memories[0]["importance"] == 5


def test_upsert_memory_empty_content(mem_db):
    assert mem_db.upsert_memory("85260000000", "") is False
    assert mem_db.upsert_memory("85260000000", "   ") is False


def test_upsert_session_memory(mem_db):
    result = mem_db.upsert_session_memory("85260000000", "User mentioned pizza")
    assert result is True
    rows = mem_db.load_session_memories("85260000000")
    assert len(rows) == 1
    assert rows[0]["content"] == "User mentioned pizza"


def test_upsert_session_memory_with_bucket(mem_db):
    mem_db.upsert_session_memory("85260000000", "A 24h memory", bucket="within_24h")
    mem_db.commit()
    rows = mem_db.load_session_memories("85260000000", bucket="within_24h")
    assert len(rows) == 1
    assert rows[0]["bucket"] == "within_24h"


def test_load_recent_messages(mem_db):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    mem_db.execute(
        "INSERT INTO wa_messages (wa_id, direction, message_id, message_type, body, raw_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("85260000000", "inbound", "msg_123", "text", "Hello", "{}", now),
    )
    mem_db.commit()
    msgs = mem_db.load_recent_messages("85260000000")
    assert len(msgs) == 1
    assert msgs[0]["body"] == "Hello"


def test_has_processed_message(mem_db):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    mem_db.execute(
        "INSERT INTO wa_messages (wa_id, direction, message_id, message_type, body, raw_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("85260000000", "inbound", "msg_processed", "text", "Hi", "{}", now),
    )
    mem_db.commit()
    assert mem_db.has_processed_message("msg_processed") is True
    assert mem_db.has_processed_message("msg_not_processed") is False


def test_count_inbound_messages(mem_db):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    for i in range(5):
        mem_db.execute(
            "INSERT INTO wa_messages (wa_id, direction, message_id, message_type, body, raw_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("85260000000", "inbound", f"msg_{i}", "text", f"Hi {i}", "{}", now),
        )
    mem_db.execute(
        "INSERT INTO wa_messages (wa_id, direction, message_id, message_type, body, raw_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("85260000000", "outbound", "msg_out", "text", "Reply", "{}", now),
    )
    mem_db.commit()
    assert mem_db.count_inbound_messages("85260000000") == 5


def test_get_last_message_time(mem_db):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    mem_db.execute(
        "INSERT INTO wa_messages (wa_id, direction, message_id, message_type, body, raw_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("85260000000", "inbound", "msg_1", "text", "Hi", "{}", now),
    )
    mem_db.commit()
    assert mem_db.get_last_message_time("85260000000") == now
    assert mem_db.get_last_message_time("85260000000", direction="outbound") is None


def test_voice_mode(mem_db):
    assert mem_db.is_voice_mode_enabled("85260000000") is False
    mem_db.set_voice_mode("85260000000", True)
    mem_db.commit()
    assert mem_db.is_voice_mode_enabled("85260000000") is True
    mem_db.set_voice_mode("85260000000", False)
    mem_db.commit()
    assert mem_db.is_voice_mode_enabled("85260000000") is False


def test_bump_image_stats(mem_db):
    mem_db.bump_image_stats("85260000000", ["photo", "photo"])
    mem_db.commit()
    stats = mem_db.load_image_stats_summary("85260000000")
    assert stats.get("photo") == 2


def test_save_and_get_reminders(mem_db):
    from datetime import datetime, timezone
    future = "2099-01-01T00:00:00+00:00"
    mem_db.save_reminder("85260000000", future, "Future reminder")
    mem_db.save_reminder("85260000000", "2099-02-01T00:00:00+00:00", "Later reminder")
    mem_db.commit()
    pending = mem_db.get_pending_reminders("85260000000", "2099-06-01T00:00:00+00:00")
    assert len(pending) == 2
    assert pending[0]["content"] == "Future reminder"
    assert pending[1]["content"] == "Later reminder"


def test_mark_reminder_fired(mem_db):
    mem_db.save_reminder("85260000000", "2099-01-01T00:00:00+00:00", "To fire")
    mem_db.commit()
    pending = mem_db.get_pending_reminders("85260000000", "2099-06-01T00:00:00+00:00")
    assert len(pending) == 1
    reminder_id = pending[0]["id"]
    mem_db.mark_reminder_fired(reminder_id)
    mem_db.commit()
    pending_after = mem_db.get_pending_reminders("85260000000", "2099-06-01T00:00:00+00:00")
    assert len(pending_after) == 0


def test_slot_success_rate_default(mem_db):
    rate = mem_db.get_slot_success_rate("85260000000", "morning_greeting")
    assert rate == 0.5


def test_file_db_persists():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        db1 = MemoryDB(db_path)
        db1.init_db()
        db1.upsert_memory("85260000000", "Persisted fact")
        db1.commit()
        db1.close()

        db2 = MemoryDB(db_path)
        db2.init_db()
        memories = db2.load_memories("85260000000")
        assert len(memories) == 1
        assert memories[0]["content"] == "Persisted fact"
        db2.close()
    finally:
        try:
            os.unlink(db_path)
        except Exception:
            pass


def test_context_manager():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        with MemoryDB(db_path) as db:
            db.init_db()
            db.upsert_memory("85260000000", "From context manager")
            db.commit()
        with MemoryDB(db_path) as db:
            db.init_db()
            memories = db.load_memories("85260000000")
            assert len(memories) == 1
    finally:
        try:
            os.unlink(db_path)
        except Exception:
            pass
