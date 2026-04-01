"""SQLite database wrapper for Susu Agent memory and state."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Any

import sys
from pathlib import Path as PathType

sys.path.insert(0, str(PathType(__file__).parent.parent.parent))


SUSU_SETTINGS_TABLE = "susu_runtime_settings"
SHORT_TERM_MEMORY_RETENTION_HOURS = 168


def utc_now():
    return datetime.now(timezone.utc)


def hk_now():
    return datetime.now(timezone.utc).astimezone()


def _normalize_key(text: str) -> str:
    import re
    cleaned = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]", "", text.lower())
    return cleaned[:100]


def _normalize_bucket(bucket: str) -> str:
    if not bucket:
        return "within_7d"
    bucket = bucket.lower().strip()
    if bucket in ("within_24h", "within_day", "day"):
        return "within_24h"
    if bucket in ("within_30d", "within_month", "month"):
        return "within_30d"
    return "within_7d"


def _short_term_expiry(observed_text: str) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=SHORT_TERM_MEMORY_RETENTION_HOURS)


def _clean_text(text: str) -> str:
    import re
    return re.sub(r"\s+", " ", (text or "")).strip()


class MemoryDB:
    """
    Centralized SQLite wrapper for all wa_agent state.
    
    Wraps connection lifecycle and provides typed methods for all
    wa_agent SQLite operations.
    """

    def __init__(self, db_path: PathType | str | None = None):
        self.db_path = Path(db_path) if db_path else None
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self) -> sqlite3.Connection:
        """Get or create the SQLite connection."""
        if self._conn is None:
            path = str(self.db_path) if self.db_path else ":memory:"
            self._conn = sqlite3.connect(path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self):
        """Close the connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def commit(self):
        """Commit current transaction."""
        if self._conn:
            self._conn.commit()

    def rollback(self):
        """Rollback current transaction."""
        if self._conn:
            self._conn.rollback()

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """Execute a SQL statement."""
        return self.connect().execute(sql, params)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def init_db(self) -> sqlite3.Connection:
        """Initialize all tables and return the connection."""
        conn = self.connect()
        self._create_tables(conn)
        conn.commit()
        return conn

    def _create_tables(self, conn: sqlite3.Connection):
        """Create all wa_agent tables."""
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS wa_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wa_id TEXT NOT NULL,
                direction TEXT NOT NULL,
                message_id TEXT NOT NULL DEFAULT '',
                message_type TEXT NOT NULL DEFAULT '',
                body TEXT NOT NULL DEFAULT '',
                raw_json TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS wa_contacts (
                wa_id TEXT PRIMARY KEY,
                profile_name TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS wa_memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wa_id TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'note',
                content TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS wa_image_stats (
                wa_id TEXT NOT NULL,
                category TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (wa_id, category)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS wa_session_memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wa_id TEXT NOT NULL,
                content TEXT NOT NULL,
                memory_key TEXT NOT NULL DEFAULT '',
                bucket TEXT NOT NULL DEFAULT 'within_7d',
                observed_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS wa_memory_archive (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wa_id TEXT NOT NULL,
                content TEXT NOT NULL,
                memory_key TEXT NOT NULL DEFAULT '',
                source_bucket TEXT NOT NULL DEFAULT 'within_7d',
                observed_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT '',
                archived_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS wa_proactive_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wa_id TEXT NOT NULL,
                slot_key TEXT NOT NULL DEFAULT '',
                trigger_type TEXT NOT NULL DEFAULT 'idle_check',
                probability REAL NOT NULL DEFAULT 0,
                score REAL NOT NULL DEFAULT 0,
                body TEXT NOT NULL DEFAULT '',
                prompt TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                responded_at TEXT NOT NULL DEFAULT '',
                response_delay_seconds INTEGER NOT NULL DEFAULT 0,
                reward REAL NOT NULL DEFAULT 0,
                outcome TEXT NOT NULL DEFAULT 'pending'
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS wa_proactive_slot_stats (
                wa_id TEXT NOT NULL,
                slot_key TEXT NOT NULL,
                success_count REAL NOT NULL DEFAULT 1,
                fail_count REAL NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (wa_id, slot_key)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS wa_claude_mode (
                wa_id TEXT PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS wa_reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wa_id TEXT NOT NULL,
                remind_at TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                fired INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        self._ensure_runtime_settings_table(conn)
        self._ensure_column(conn, "wa_session_memories", "bucket", "bucket TEXT NOT NULL DEFAULT 'within_7d'")
        self._ensure_column(conn, "wa_session_memories", "observed_at", "observed_at TEXT NOT NULL DEFAULT ''")
        self._ensure_column(conn, "wa_memories", "memory_key", "memory_key TEXT NOT NULL DEFAULT ''")
        self._ensure_column(conn, "wa_memories", "created_at", "created_at TEXT NOT NULL DEFAULT ''")
        self._ensure_column(conn, "wa_memories", "importance", "importance INTEGER NOT NULL DEFAULT 3")
        conn.execute("UPDATE wa_memories SET created_at = updated_at WHERE created_at = ''")
        self._normalize_recent_memory_rows(conn)
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_wa_memories_unique ON wa_memories (wa_id, memory_key)"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_wa_session_memories_unique ON wa_session_memories (wa_id, memory_key)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_wa_session_memories_bucket ON wa_session_memories (wa_id, bucket, updated_at DESC)"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_wa_memory_archive_unique ON wa_memory_archive (wa_id, memory_key, observed_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_wa_memory_archive_lookup ON wa_memory_archive (wa_id, archived_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_wa_memory_archive_observed ON wa_memory_archive (wa_id, observed_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_wa_proactive_events_lookup ON wa_proactive_events (wa_id, outcome, created_at DESC)"
        )
        self._archive_expired_session_memories(conn)

    def _ensure_column(self, conn: sqlite3.Connection, table_name: str, column_name: str, ddl: str):
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
        if column_name not in columns:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {ddl}")

    def _ensure_runtime_settings_table(self, conn: sqlite3.Connection):
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {SUSU_SETTINGS_TABLE} (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            )
            """
        )

    def _normalize_recent_memory_rows(self, conn: sqlite3.Connection):
        rows = conn.execute(
            "SELECT id, bucket, content, memory_key, observed_at, updated_at, expires_at FROM wa_session_memories"
        ).fetchall()
        for row in rows:
            bucket = _normalize_bucket(row["bucket"])
            now = datetime.now(timezone.utc)
            observed = self._parse_iso_dt(row["observed_at"] or row["updated_at"]) or now
            observed_text = observed.astimezone(timezone.utc).isoformat()
            expires_text = _short_term_expiry(observed_text).isoformat()
            scoped_key = f"{bucket}:{_normalize_key(row['content'])}"
            if (
                row["bucket"] != bucket
                or _clean_text(row["observed_at"]) != observed_text
                or _clean_text(row["expires_at"]) != expires_text
                or _clean_text(row["memory_key"]) != scoped_key
            ):
                conn.execute(
                    "UPDATE wa_session_memories SET bucket=?, observed_at=?, expires_at=?, memory_key=? WHERE id=?",
                    (bucket, observed_text, expires_text, scoped_key, row["id"]),
                )

    def _archive_expired_session_memories(self, conn: sqlite3.Connection, now=None):
        now_utc = (now or hk_now()).astimezone(timezone.utc)
        rows = conn.execute(
            "SELECT id, wa_id, content, memory_key, bucket, observed_at, updated_at, expires_at FROM wa_session_memories WHERE expires_at != '' AND expires_at <= ? ORDER BY observed_at ASC, id ASC",
            (now_utc.isoformat(),),
        ).fetchall()
        for row in rows:
            content = _clean_text(row["content"])
            archive_key = _normalize_key(content)
            if not content or not archive_key:
                conn.execute("DELETE FROM wa_session_memories WHERE id=?", (row["id"],))
                continue
            observed = self._parse_iso_dt(row["observed_at"] or row["updated_at"]) or now_utc
            observed_text = observed.astimezone(timezone.utc).isoformat()
            updated_text = _clean_text(row["updated_at"]) or observed_text
            archived_at = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """
                INSERT INTO wa_memory_archive (wa_id, content, memory_key, source_bucket, observed_at, updated_at, archived_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(wa_id, memory_key, observed_at) DO UPDATE SET
                    content=excluded.content, source_bucket=excluded.source_bucket,
                    updated_at=excluded.updated_at, archived_at=excluded.archived_at
                """,
                (row["wa_id"], content, archive_key, row["bucket"], observed_text, updated_text, archived_at),
            )
            conn.execute("DELETE FROM wa_session_memories WHERE id=?", (row["id"],))

    def _parse_iso_dt(self, text: str) -> Optional[datetime]:
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None

    def ensure_db_path(self, base_dir: PathType | str):
        """Set DB path from base directory."""
        self.db_path = Path(base_dir) / "wa_agent.db"

    def get_connection(self) -> sqlite3.Connection:
        """Get the connection (init if needed)."""
        conn = self.connect()
        try:
            conn.execute("SELECT 1")
        except sqlite3.OperationalError:
            self.init_db()
        return self.connect()

    def load_memories(self, wa_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """Load long-term memories for a wa_id."""
        rows = self.execute(
            "SELECT kind, content, importance, updated_at, created_at FROM wa_memories WHERE wa_id=? ORDER BY importance DESC, updated_at DESC, id DESC LIMIT ?",
            (wa_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def upsert_memory(self, wa_id: str, content: str, kind: str = "note", importance: int = 3) -> bool:
        """Upsert a long-term memory."""
        text = _clean_text(content)
        if not text:
            return False
        key = _normalize_key(text)
        if not key:
            return False
        importance = max(1, min(5, int(importance or 3)))
        now = utc_now().isoformat()
        self.execute(
            """
            INSERT INTO wa_memories (wa_id, kind, content, memory_key, importance, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(wa_id, memory_key) DO UPDATE SET
                kind=excluded.kind, content=excluded.content,
                importance=MAX(importance, excluded.importance), updated_at=excluded.updated_at
            """,
            (wa_id, kind, text, key, importance, now, now),
        )
        return True

    def upsert_session_memory(
        self,
        wa_id: str,
        content: str,
        bucket: str = "within_7d",
        ttl_hours: int | None = None,
        observed_at: str | None = None,
    ) -> bool:
        """Upsert a session memory with TTL."""
        text = _clean_text(content)
        if not text:
            return False
        key = _normalize_key(text)
        if not key:
            return False
        bucket = _normalize_bucket(bucket)
        now = datetime.now(timezone.utc)
        observed = self._parse_iso_dt(observed_at) or now
        if ttl_hours is None:
            ttl_hours = SHORT_TERM_MEMORY_RETENTION_HOURS
        scoped_key = f"{bucket}:{key}"
        expires_at = (observed.astimezone(timezone.utc) + timedelta(hours=ttl_hours)).isoformat()
        observed_at_text = observed.astimezone(timezone.utc).isoformat()
        now_text = now.isoformat()
        self.execute(
            """
            INSERT INTO wa_session_memories (wa_id, content, memory_key, bucket, observed_at, updated_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(wa_id, memory_key) DO UPDATE SET
                content=excluded.content, bucket=excluded.bucket,
                observed_at=excluded.observed_at, updated_at=excluded.updated_at, expires_at=excluded.expires_at
            """,
            (wa_id, text, scoped_key, bucket, observed_at_text, now_text, expires_at),
        )
        return True

    def load_session_memories(self, wa_id: str, limit: int = 8, bucket: str | None = None) -> list[dict[str, Any]]:
        """Load session memories."""
        if bucket:
            rows = self.execute(
                "SELECT content, memory_key, bucket, observed_at FROM wa_session_memories WHERE wa_id=? AND bucket=? ORDER BY observed_at DESC LIMIT ?",
                (wa_id, bucket, limit),
            ).fetchall()
        else:
            rows = self.execute(
                "SELECT content, memory_key, bucket, observed_at FROM wa_session_memories WHERE wa_id=? ORDER BY observed_at DESC LIMIT ?",
                (wa_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def load_recent_messages(self, wa_id: str, limit: int = 12) -> list[dict[str, Any]]:
        """Load recent messages."""
        rows = self.execute(
            "SELECT id, direction, message_id, message_type, body, raw_json, created_at FROM wa_messages WHERE wa_id=? ORDER BY id DESC LIMIT ?",
            (wa_id, limit),
        ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def has_processed_message(self, message_id: str) -> bool:
        """Check if a message has been processed."""
        row = self.execute(
            "SELECT 1 FROM wa_messages WHERE message_id=? LIMIT 1",
            (message_id,),
        ).fetchone()
        return row is not None

    def get_last_message_time(self, wa_id: str, direction: str | None = None) -> str | None:
        """Get the last message timestamp."""
        if direction:
            row = self.execute(
                "SELECT created_at FROM wa_messages WHERE wa_id=? AND direction=? ORDER BY id DESC LIMIT 1",
                (wa_id, direction),
            ).fetchone()
        else:
            row = self.execute(
                "SELECT created_at FROM wa_messages WHERE wa_id=? ORDER BY id DESC LIMIT 1",
                (wa_id,),
            ).fetchone()
        return row["created_at"] if row else None

    def count_inbound_messages(self, wa_id: str) -> int:
        """Count inbound messages for a wa_id."""
        row = self.execute(
            "SELECT COUNT(*) as c FROM wa_messages WHERE wa_id=? AND direction='inbound'",
            (wa_id,),
        ).fetchone()
        return row["c"] if row else 0

    def get_pending_proactive_event(self, wa_id: str) -> dict | None:
        """Get a pending proactive event."""
        row = self.execute(
            "SELECT * FROM wa_proactive_events WHERE wa_id=? AND outcome='pending' ORDER BY score DESC LIMIT 1",
            (wa_id,),
        ).fetchone()
        return dict(row) if row else None

    def mark_proactive_reply(self, wa_id: str, inbound_at_text: str) -> bool:
        """Mark proactive event as responded."""
        row = self.execute(
            "SELECT id FROM wa_proactive_events WHERE wa_id=? AND outcome='pending' ORDER BY score DESC LIMIT 1",
            (wa_id,),
        ).fetchone()
        if not row:
            return False
        self.execute(
            "UPDATE wa_proactive_events SET outcome='replied', responded_at=? WHERE id=?",
            (inbound_at_text, row["id"]),
        )
        return True

    def get_slot_success_rate(self, wa_id: str, slot_key: str) -> float:
        """Get success rate for a proactive slot."""
        row = self.execute(
            "SELECT success_count, fail_count FROM wa_proactive_slot_stats WHERE wa_id=? AND slot_key=?",
            (wa_id, slot_key),
        ).fetchone()
        if not row or (row["success_count"] + row["fail_count"]) == 0:
            return 0.5
        return row["success_count"] / (row["success_count"] + row["fail_count"])

    def bump_image_stats(self, wa_id: str, categories: list[str]) -> bool:
        """Bump image stats counters."""
        now = utc_now().isoformat()
        for cat in categories:
            self.execute(
                "INSERT INTO wa_image_stats (wa_id, category, count, updated_at) VALUES (?, ?, 1, ?) ON CONFLICT(wa_id, category) DO UPDATE SET count=count+1, updated_at=excluded.updated_at",
                (wa_id, cat, now),
            )
        return True

    def load_image_stats_summary(self, wa_id: str) -> dict[str, int]:
        """Load image stats summary."""
        rows = self.execute(
            "SELECT category, count FROM wa_image_stats WHERE wa_id=?", (wa_id,)
        ).fetchall()
        return {row["category"]: row["count"] for row in rows}

    def is_voice_mode_enabled(self, wa_id: str) -> bool:
        """Check if voice mode is enabled for a wa_id."""
        row = self.execute(
            "SELECT content FROM wa_memories WHERE wa_id=? AND memory_key='voice_mode' LIMIT 1",
            (wa_id,)
        ).fetchone()
        return bool(row and row["content"] == "on")

    def set_voice_mode(self, wa_id: str, enabled: bool = True) -> bool:
        """Set voice mode for a wa_id."""
        now = utc_now().isoformat()
        self.execute(
            "INSERT INTO wa_memories (wa_id, kind, content, memory_key, created_at, updated_at) VALUES (?, 'setting', ?, 'voice_mode', ?, ?) ON CONFLICT(wa_id, memory_key) DO UPDATE SET content=excluded.content, updated_at=excluded.updated_at",
            (wa_id, "on" if enabled else "off", now, now),
        )
        return True

    def save_reminder(self, wa_id: str, remind_at_iso: str, content: str) -> bool:
        """Save a reminder."""
        now = utc_now().isoformat()
        self.execute(
            "INSERT INTO wa_reminders (wa_id, remind_at, content, created_at) VALUES (?, ?, ?, ?)",
            (wa_id, remind_at_iso, content, now),
        )
        return True

    def get_pending_reminders(self, wa_id: str, now_iso: str) -> list[dict]:
        """Get pending reminders that should fire (remind_at <= now_iso)."""
        rows = self.execute(
            "SELECT id, remind_at, content FROM wa_reminders WHERE wa_id=? AND fired=0 AND remind_at <= ? ORDER BY remind_at ASC",
            (wa_id, now_iso),
        ).fetchall()
        return [dict(row) for row in rows]

    def mark_reminder_fired(self, reminder_id: int) -> bool:
        """Mark a reminder as fired."""
        self.execute("UPDATE wa_reminders SET fired=1 WHERE id=?", (reminder_id,))
        return True
