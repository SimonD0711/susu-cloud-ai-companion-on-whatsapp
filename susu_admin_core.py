#!/usr/bin/env python3
import difflib
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


BASE_DIR = Path(os.environ.get("SUSU_BASE_DIR", "/var/www/html"))
WA_AGENT_DB_PATH = BASE_DIR / "wa_agent.db"
SUSU_PRIMARY_WA_ID = os.environ.get("WA_ADMIN_WA_ID", "85259576670")
SUSU_SETTINGS_TABLE = "wa_susu_settings"
SHORT_TERM_MEMORY_RETENTION_HOURS = 24 * 7
SESSION_BUCKET_LABELS = {
    "within_24h": "24小時內",
    "within_3d": "三天內",
    "within_7d": "一週內",
    "today": "24小時內",
    "last_night": "三天內",
    "recent_days": "一週內",
}
SUSU_SETTING_SPECS = {
    "system_persona": {"type": "multiline", "max_length": 12000, "default": "", "required": True},
    "primary_user_memory": {"type": "multiline", "max_length": 12000, "default": "", "required": True},
    "proactive_enabled": {"type": "bool", "default": True},
    "proactive_scan_seconds": {"type": "int", "default": int(os.environ.get("WA_PROACTIVE_SCAN_SECONDS", "300")), "min": 60, "max": 3600},
    "proactive_min_silence_minutes": {"type": "int", "default": int(os.environ.get("WA_PROACTIVE_MIN_SILENCE_MINUTES", "45")), "min": 5, "max": 1440},
    "proactive_cooldown_minutes": {"type": "int", "default": int(os.environ.get("WA_PROACTIVE_COOLDOWN_MINUTES", "180")), "min": 10, "max": 2880},
    "proactive_reply_window_minutes": {"type": "int", "default": int(os.environ.get("WA_PROACTIVE_REPLY_WINDOW_MINUTES", "90")), "min": 10, "max": 1440},
    "proactive_conversation_window_hours": {"type": "int", "default": int(os.environ.get("WA_PROACTIVE_CONVERSATION_WINDOW_HOURS", "24")), "min": 1, "max": 168},
    "proactive_max_per_service_day": {"type": "int", "default": int(os.environ.get("WA_PROACTIVE_MAX_PER_SERVICE_DAY", "2")), "min": 0, "max": 20},
    "proactive_min_inbound_messages": {"type": "int", "default": int(os.environ.get("WA_PROACTIVE_MIN_INBOUND_MESSAGES", "8")), "min": 1, "max": 200},
}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def get_wa_agent_db():
    conn = sqlite3.connect(WA_AGENT_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def wa_table_exists(conn, table_name):
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return bool(row)


def susu_clean_text(value):
    return re.sub(r"\s+", " ", str(value or "").strip())


def susu_normalize_key(value):
    value = susu_clean_text(value).lower()
    value = re.sub(r"[^\w\u4e00-\u9fff]+", "", value)
    return value[:160]


def parse_iso_text(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def current_session_bucket(observed_at, now_utc=None):
    observed = parse_iso_text(observed_at)
    if not observed:
        return "within_7d"
    now_utc = now_utc or datetime.now(timezone.utc)
    age = now_utc - observed
    if age <= timedelta(hours=24):
        return "within_24h"
    if age <= timedelta(hours=72):
        return "within_3d"
    if age <= timedelta(hours=SHORT_TERM_MEMORY_RETENTION_HOURS):
        return "within_7d"
    return ""


def split_susu_memory_lines(value):
    lines = []
    for raw_line in str(value or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = re.sub(r"^\s*[-*•]+\s*", "", raw_line).strip()
        line = susu_clean_text(line)
        if line:
            lines.append(line)
    return lines


def susu_memories_look_duplicated(left, right):
    left_key = susu_normalize_key(left)
    right_key = susu_normalize_key(right)
    if not left_key or not right_key:
        return False
    if left_key == right_key:
        return True
    shorter, longer = (left_key, right_key) if len(left_key) <= len(right_key) else (right_key, left_key)
    if len(shorter) >= 10 and shorter in longer:
        return True
    if len(shorter) >= 8 and difflib.SequenceMatcher(None, left_key, right_key).ratio() >= 0.78:
        return True
    return False


def normalize_susu_multiline(value, fallback=""):
    text = str(fallback if value is None else value).replace("\r\n", "\n").replace("\r", "\n").strip()
    return re.sub(r"\n{3,}", "\n\n", text)


def normalize_susu_text(value, fallback=""):
    return re.sub(r"\s+", " ", str(fallback if value is None else value).strip())


def compact_primary_user_memory_text(value, max_lines=10, max_chars=1800):
    kept = []
    current_chars = 0
    for line in split_susu_memory_lines(value):
        if any(susu_memories_look_duplicated(line, existing) for existing in kept):
            continue
        next_chars = current_chars + len(line) + 2
        if kept and next_chars > max_chars:
            break
        kept.append(line)
        current_chars = next_chars
        if len(kept) >= max_lines:
            break
    if not kept:
        return normalize_susu_multiline(value)
    return "\n".join(f"- {line}" for line in kept)


def parse_susu_bool(value, default=False):
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def parse_susu_int(value, default=0, minimum=None, maximum=None):
    try:
        parsed = int(str(value).strip())
    except Exception:
        parsed = int(default)
    if minimum is not None:
        parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def coerce_susu_setting_value(key, raw_value):
    spec = SUSU_SETTING_SPECS[key]
    setting_type = spec["type"]
    default = spec["default"]
    if setting_type == "bool":
        return parse_susu_bool(raw_value, default)
    if setting_type == "int":
        return parse_susu_int(raw_value, default, spec.get("min"), spec.get("max"))
    if setting_type == "multiline":
        text = normalize_susu_multiline(raw_value, default)[: spec.get("max_length", 12000)]
        if key == "primary_user_memory":
            return compact_primary_user_memory_text(text)[: spec.get("max_length", 12000)]
        return text
    return normalize_susu_text(raw_value, default)[: spec.get("max_length", 255)]


def serialize_susu_setting_value(key, raw_value):
    value = coerce_susu_setting_value(key, raw_value)
    if SUSU_SETTING_SPECS[key]["type"] == "bool":
        return "1" if value else "0"
    return str(value)


def ensure_susu_settings_table(conn):
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SUSU_SETTINGS_TABLE} (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        )
        """
    )
    seeded_at = utc_now()
    for key, spec in SUSU_SETTING_SPECS.items():
        conn.execute(
            f"""
            INSERT OR IGNORE INTO {SUSU_SETTINGS_TABLE} (key, value, updated_at)
            VALUES (?, ?, ?)
            """,
            (key, serialize_susu_setting_value(key, spec["default"]), seeded_at),
        )


def fetch_susu_settings_with_conn(conn):
    ensure_susu_settings_table(conn)
    conn.commit()
    rows = conn.execute(f"SELECT key, value, updated_at FROM {SUSU_SETTINGS_TABLE}").fetchall()
    row_map = {row["key"]: row for row in rows}
    updated_at = ""
    values = {}
    for key, spec in SUSU_SETTING_SPECS.items():
        row = row_map.get(key)
        values[key] = coerce_susu_setting_value(key, row["value"] if row else spec["default"])
        if row and row["updated_at"] and row["updated_at"] > updated_at:
            updated_at = row["updated_at"]
    return {"values": values, "updated_at": updated_at}


def update_susu_settings(changes):
    if not isinstance(changes, dict) or not changes:
        return {"ok": False, "detail": "Missing settings"}
    unsupported = [key for key in changes if key not in SUSU_SETTING_SPECS]
    if unsupported:
        return {"ok": False, "detail": f"Unsupported setting: {unsupported[0]}"}
    now = utc_now()
    conn = get_wa_agent_db()
    try:
        ensure_susu_settings_table(conn)
        for key, raw_value in changes.items():
            spec = SUSU_SETTING_SPECS[key]
            value = coerce_susu_setting_value(key, raw_value)
            if spec.get("required") and not str(value).strip():
                return {"ok": False, "detail": f"Missing value for {key}"}
            conn.execute(
                f"""
                INSERT INTO {SUSU_SETTINGS_TABLE} (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                  value = excluded.value,
                  updated_at = excluded.updated_at
                """,
                (key, serialize_susu_setting_value(key, value), now),
            )
        conn.commit()
        return {"ok": True, "updated_at": now}
    finally:
        conn.close()


def dedupe_primary_long_term_memories(wa_id=SUSU_PRIMARY_WA_ID):
    conn = get_wa_agent_db()
    try:
        settings = fetch_susu_settings_with_conn(conn)["values"]
        primary_lines = split_susu_memory_lines(settings.get("primary_user_memory", ""))
        if not primary_lines:
            return {"ok": True, "removed_count": 0, "removed_items": []}
        rows = conn.execute(
            """
            SELECT id, content
            FROM wa_memories
            WHERE wa_id = ?
            ORDER BY updated_at DESC, id DESC
            """,
            (wa_id,),
        ).fetchall()
        removed_ids = []
        removed_items = []
        seen = []
        for row in rows:
            content = susu_clean_text(row["content"])
            if not content:
                continue
            if any(susu_memories_look_duplicated(content, item) for item in seen):
                removed_ids.append(row["id"])
                removed_items.append(content)
                continue
            if any(susu_memories_look_duplicated(content, primary_line) for primary_line in primary_lines):
                removed_ids.append(row["id"])
                removed_items.append(content)
                continue
            seen.append(content)
        if removed_ids:
            conn.executemany("DELETE FROM wa_memories WHERE id = ?", [(entry_id,) for entry_id in removed_ids])
            conn.commit()
        return {"ok": True, "removed_count": len(removed_ids), "removed_items": removed_items[:20]}
    finally:
        conn.close()


def fetch_susu_contacts(conn):
    archive_enabled = wa_table_exists(conn, "wa_memory_archive")
    row = conn.execute(
        """
        SELECT wa_id, profile_name, updated_at
        FROM wa_contacts
        WHERE wa_id = ?
        LIMIT 1
        """,
        (SUSU_PRIMARY_WA_ID,),
    ).fetchone()
    profile_name = row["profile_name"] if row else ""
    updated_at = row["updated_at"] if row else ""
    archive_count = 0
    if archive_enabled:
        archive_count = int(
            conn.execute(
                "SELECT COUNT(*) AS total FROM wa_memory_archive WHERE wa_id = ?",
                (SUSU_PRIMARY_WA_ID,),
            ).fetchone()["total"]
        )
    counts = conn.execute(
        """
        SELECT
          (SELECT COUNT(*) FROM wa_memories WHERE wa_id = ?) AS memory_count,
          (SELECT COUNT(*) FROM wa_session_memories WHERE wa_id = ?) AS session_count,
          (SELECT COUNT(*) FROM wa_reminders WHERE wa_id = ?) AS reminder_count,
          (SELECT COUNT(*) FROM wa_reminders WHERE wa_id = ? AND fired = 0) AS pending_reminder_count
        """,
        (SUSU_PRIMARY_WA_ID, SUSU_PRIMARY_WA_ID, SUSU_PRIMARY_WA_ID, SUSU_PRIMARY_WA_ID),
    ).fetchone()
    return [
        {
            "wa_id": SUSU_PRIMARY_WA_ID,
            "profile_name": profile_name,
            "updated_at": updated_at,
            "display_name": profile_name or SUSU_PRIMARY_WA_ID,
            "memory_count": int(counts["memory_count"]),
            "session_count": int(counts["session_count"]),
            "archive_count": archive_count,
            "reminder_count": int(counts["reminder_count"]),
            "pending_reminder_count": int(counts["pending_reminder_count"]),
        }
    ]


def fetch_susu_memory(selected_wa_id=""):
    conn = get_wa_agent_db()
    try:
        archive_enabled = wa_table_exists(conn, "wa_memory_archive")
        contacts = fetch_susu_contacts(conn)
        selected_wa_id = SUSU_PRIMARY_WA_ID

        memories = []
        session_memories = []
        archived_memories = []
        reminders = []
        if selected_wa_id:
            memories = [
                {
                    "id": row["id"],
                    "wa_id": row["wa_id"],
                    "kind": row["kind"] or "note",
                    "content": row["content"] or "",
                    "memory_key": row["memory_key"] or "",
                    "created_at": row["created_at"] or "",
                    "updated_at": row["updated_at"] or "",
                }
                for row in conn.execute(
                    """
                    SELECT id, wa_id, kind, content, memory_key, created_at, updated_at
                    FROM wa_memories
                    WHERE wa_id = ?
                    ORDER BY updated_at DESC, id DESC
                    """,
                    (selected_wa_id,),
                ).fetchall()
            ]
            now_utc = datetime.now(timezone.utc)
            session_memories = []
            for row in conn.execute(
                """
                SELECT id, wa_id, bucket, content, memory_key, observed_at, updated_at, expires_at
                FROM wa_session_memories
                WHERE wa_id = ?
                ORDER BY updated_at DESC, id DESC
                """,
                (selected_wa_id,),
            ).fetchall():
                expires_at = parse_iso_text(row["expires_at"])
                observed_at = row["observed_at"] or row["updated_at"] or ""
                current_bucket = current_session_bucket(observed_at, now_utc)
                session_memories.append(
                    {
                        "id": row["id"],
                        "wa_id": row["wa_id"],
                        "bucket": current_bucket or (row["bucket"] or "within_7d"),
                        "bucket_label": SESSION_BUCKET_LABELS.get(current_bucket or (row["bucket"] or "within_7d"), current_bucket or (row["bucket"] or "within_7d")),
                        "source_bucket": row["bucket"] or "within_7d",
                        "content": row["content"] or "",
                        "memory_key": row["memory_key"] or "",
                        "observed_at": observed_at,
                        "updated_at": row["updated_at"] or "",
                        "expires_at": row["expires_at"] or "",
                        "is_expired": bool(expires_at and expires_at <= now_utc),
                    }
                )
            if archive_enabled:
                archived_memories = [
                    {
                        "id": row["id"],
                        "wa_id": row["wa_id"],
                        "content": row["content"] or "",
                        "memory_key": row["memory_key"] or "",
                        "source_bucket": row["source_bucket"] or "within_7d",
                        "source_bucket_label": SESSION_BUCKET_LABELS.get(row["source_bucket"] or "within_7d", row["source_bucket"] or "within_7d"),
                        "observed_at": row["observed_at"] or "",
                        "updated_at": row["updated_at"] or "",
                        "archived_at": row["archived_at"] or "",
                    }
                    for row in conn.execute(
                        """
                        SELECT id, wa_id, content, memory_key, source_bucket, observed_at, updated_at, archived_at
                        FROM wa_memory_archive
                        WHERE wa_id = ?
                        ORDER BY observed_at DESC, archived_at DESC, id DESC
                        """,
                        (selected_wa_id,),
                    ).fetchall()
                ]
            reminders = [
                {
                    "id": row["id"],
                    "wa_id": row["wa_id"],
                    "remind_at": row["remind_at"] or "",
                    "content": row["content"] or "",
                    "created_at": row["created_at"] or "",
                    "fired": bool(row["fired"]),
                }
                for row in conn.execute(
                    """
                    SELECT id, wa_id, remind_at, content, created_at, fired
                    FROM wa_reminders
                    WHERE wa_id = ?
                    ORDER BY remind_at ASC, id ASC
                    """,
                    (selected_wa_id,),
                ).fetchall()
            ]

        selected_contact = next((item for item in contacts if item["wa_id"] == selected_wa_id), None)
        return {
            "checked_at": utc_now(),
            "selected_wa_id": selected_wa_id,
            "selected_contact": selected_contact,
            "susu_settings": fetch_susu_settings_with_conn(conn),
            "contacts": contacts,
            "long_term_memories": memories,
            "session_memories": session_memories,
            "archived_memories": archived_memories,
            "reminders": reminders,
            "stats": {
                "long_term_count": len(memories),
                "session_count": len(session_memories),
                "active_session_count": sum(1 for item in session_memories if not item["is_expired"]),
                "recent_24h_count": sum(1 for item in session_memories if item["bucket"] == "within_24h" and not item["is_expired"]),
                "recent_3d_count": sum(1 for item in session_memories if item["bucket"] == "within_3d" and not item["is_expired"]),
                "recent_7d_count": sum(1 for item in session_memories if item["bucket"] == "within_7d" and not item["is_expired"]),
                "archive_count": len(archived_memories),
                "reminder_count": len(reminders),
                "pending_reminder_count": sum(1 for item in reminders if not item["fired"]),
            },
        }
    finally:
        conn.close()


def create_susu_memory(wa_id, content, kind="manual"):
    wa_id = SUSU_PRIMARY_WA_ID
    content = susu_clean_text(content)
    kind = susu_clean_text(kind)[:40] or "manual"
    if not wa_id or not content:
        return {"ok": False, "detail": "Missing wa_id or content"}
    memory_key = susu_normalize_key(content)
    if not memory_key:
        return {"ok": False, "detail": "Invalid content"}
    now = utc_now()
    conn = get_wa_agent_db()
    try:
        conn.execute(
            """
            INSERT INTO wa_memories (wa_id, kind, content, memory_key, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(wa_id, memory_key) DO UPDATE SET
              kind = excluded.kind,
              content = excluded.content,
              updated_at = excluded.updated_at
            """,
            (wa_id, kind, content, memory_key, now, now),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id FROM wa_memories WHERE wa_id = ? AND memory_key = ?",
            (wa_id, memory_key),
        ).fetchone()
        return {"ok": True, "id": row["id"] if row else None}
    finally:
        conn.close()


def update_susu_memory(entry_id, content, kind="", importance=None):
    entry_id = int(entry_id or 0)
    content = susu_clean_text(content)
    if not entry_id or not content:
        return {"ok": False, "detail": "Missing id or content"}
    conn = get_wa_agent_db()
    try:
        row = conn.execute(
            "SELECT id, wa_id, kind FROM wa_memories WHERE id = ?",
            (entry_id,),
        ).fetchone()
        if not row:
            return {"ok": False, "detail": "Memory not found"}
        next_kind = susu_clean_text(kind)[:40] or row["kind"] or "manual"
        next_key = susu_normalize_key(content)
        if not next_key:
            return {"ok": False, "detail": "Invalid content"}
        now = utc_now()
        duplicate = conn.execute(
            "SELECT id FROM wa_memories WHERE wa_id = ? AND memory_key = ? AND id != ?",
            (row["wa_id"], next_key, entry_id),
        ).fetchone()
        if duplicate:
            dup_importance = conn.execute(
                "SELECT importance FROM wa_memories WHERE id = ?",
                (duplicate["id"],),
            ).fetchone()
            merged_importance = dup_importance["importance"]
            if importance is not None and importance > (merged_importance or 0):
                merged_importance = importance
            conn.execute(
                """
                UPDATE wa_memories
                SET kind = ?, content = ?, updated_at = ?, importance = ?
                WHERE id = ?
                """,
                (next_kind, content, now, merged_importance, duplicate["id"]),
            )
            conn.execute("DELETE FROM wa_memories WHERE id = ?", (entry_id,))
            target_id = duplicate["id"]
        else:
            conn.execute(
                """
                UPDATE wa_memories
                SET kind = ?, content = ?, memory_key = ?, updated_at = ?, importance = ?
                WHERE id = ?
                """,
                (next_kind, content, next_key, now, importance if importance is not None else row.get("importance"), entry_id),
            )
            target_id = entry_id
        conn.commit()
        return {"ok": True, "id": target_id}
    finally:
        conn.close()


def update_susu_reminder(entry_id, remind_at, content):
    entry_id = int(entry_id or 0)
    content = susu_clean_text(content)
    remind_at = str(remind_at or "").strip()
    if not entry_id or not remind_at or not content:
        return {"ok": False, "detail": "Missing id, remind_at or content"}
    try:
        parsed = datetime.fromisoformat(remind_at.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone(timedelta(hours=8)))
    except Exception:
        parsed = None
    if not parsed:
        return {"ok": False, "detail": "Invalid remind_at"}
    stored_remind_at = parsed.isoformat()
    conn = get_wa_agent_db()
    try:
        row = conn.execute("SELECT id FROM wa_reminders WHERE id = ?", (entry_id,)).fetchone()
        if not row:
            return {"ok": False, "detail": "Reminder not found"}
        conn.execute(
            """
            UPDATE wa_reminders
            SET remind_at = ?, content = ?
            WHERE id = ?
            """,
            (stored_remind_at, content, entry_id),
        )
        conn.commit()
        return {"ok": True, "id": entry_id}
    finally:
        conn.close()


def delete_susu_memory(entry_id, item_type="memory"):
    entry_id = int(entry_id or 0)
    if not entry_id:
        return {"ok": False, "detail": "Missing id"}
    table_map = {
        "memory": "wa_memories",
        "session": "wa_session_memories",
        "archive": "wa_memory_archive",
        "reminder": "wa_reminders",
    }
    table_name = table_map.get((item_type or "").strip(), "")
    if not table_name:
        return {"ok": False, "detail": "Unsupported type"}
    conn = get_wa_agent_db()
    try:
        result = conn.execute(f"DELETE FROM {table_name} WHERE id = ?", (entry_id,))
        conn.commit()
        return {"ok": result.rowcount > 0}
    finally:
        conn.close()
