#!/usr/bin/env python3
import base64
import difflib
import hashlib
import hmac
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from env_utils import load_dotenv

load_dotenv()

from wa_agent import (
    ADMIN_WA_ID,
    DB_PATH,
    GEMINI_MODEL,
    PRIMARY_USER_MEMORY,
    PROACTIVE_CONVERSATION_WINDOW_HOURS,
    PROACTIVE_COOLDOWN_MINUTES,
    PROACTIVE_ENABLED,
    PROACTIVE_MAX_PER_SERVICE_DAY,
    PROACTIVE_MIN_INBOUND_MESSAGES,
    PROACTIVE_MIN_SILENCE_MINUTES,
    PROACTIVE_REPLY_WINDOW_MINUTES,
    PROACTIVE_SCAN_SECONDS,
    RELAY_FALLBACK_MODEL,
    RELAY_MODEL,
    SYSTEM_PERSONA,
    get_db as get_wa_agent_db,
    utc_now,
)


PROJECT_DIR = Path(__file__).resolve().parent
ADMIN_UI_PATH = PROJECT_DIR / "susu-memory-admin.html"

ADMIN_NAME = os.environ.get("SUSU_ADMIN_NAME", "Susu Admin")
ADMIN_PASSWORD_SALT_B64 = os.environ.get("SUSU_ADMIN_PASSWORD_SALT_B64", "")
ADMIN_PASSWORD_HASH_B64 = os.environ.get("SUSU_ADMIN_PASSWORD_HASH_B64", "")
ADMIN_SESSION_SECRET = os.environ.get("SUSU_ADMIN_SESSION_SECRET", "")
ADMIN_SESSION_COOKIE = os.environ.get("SUSU_ADMIN_SESSION_COOKIE", "susu_admin_session")
ADMIN_SESSION_TTL = int(os.environ.get("SUSU_ADMIN_SESSION_TTL", str(60 * 60 * 24 * 30)))
ADMIN_SECURE_COOKIE = os.environ.get("SUSU_ADMIN_SECURE_COOKIE", "0").strip().lower() in {"1", "true", "yes", "on"}
ADMIN_HOST = os.environ.get("SUSU_ADMIN_HOST", "127.0.0.1")
ADMIN_PORT = int(os.environ.get("SUSU_ADMIN_PORT", "9000"))

SESSION_BUCKET_LABELS = {
    "within_24h": "24小時內",
    "within_3d": "三天內",
    "within_7d": "一週內",
    "today": "24小時內",
    "last_night": "三天內",
    "recent_days": "一週內",
}
SHORT_TERM_MEMORY_RETENTION_HOURS = 24 * 7


def parse_cookies(handler):
    cookie_header = handler.headers.get("Cookie", "")
    cookies = {}
    for item in cookie_header.split(";"):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        cookies[key.strip()] = value.strip()
    return cookies


def admin_login_ready():
    return bool(
        ADMIN_PASSWORD_SALT_B64.strip()
        and ADMIN_PASSWORD_HASH_B64.strip()
        and ADMIN_SESSION_SECRET.strip()
    )


def sign_admin_session(expires_at):
    message = f"admin|{expires_at}".encode("utf-8")
    return hmac.new(ADMIN_SESSION_SECRET.encode("utf-8"), message, hashlib.sha256).hexdigest()


def make_admin_session_cookie():
    expires_at = int(time.time()) + ADMIN_SESSION_TTL
    signature = sign_admin_session(expires_at)
    token = base64.urlsafe_b64encode(f"{expires_at}:{signature}".encode("utf-8")).decode("ascii")
    cookie = (
        f"{ADMIN_SESSION_COOKIE}={token}; Max-Age={ADMIN_SESSION_TTL}; "
        f"Path=/; HttpOnly; SameSite=Lax"
    )
    if ADMIN_SECURE_COOKIE:
        cookie += "; Secure"
    return cookie


def clear_admin_session_cookie():
    cookie = f"{ADMIN_SESSION_COOKIE}=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax"
    if ADMIN_SECURE_COOKIE:
        cookie += "; Secure"
    return cookie


def is_admin_authenticated(handler):
    if not admin_login_ready():
        return False
    token = parse_cookies(handler).get(ADMIN_SESSION_COOKIE)
    if not token:
        return False
    try:
        decoded = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
        expires_at_raw, signature = decoded.split(":", 1)
        expires_at = int(expires_at_raw)
    except Exception:
        return False
    if expires_at < int(time.time()):
        return False
    return hmac.compare_digest(signature, sign_admin_session(expires_at))


def verify_admin_password(password):
    if not admin_login_ready():
        return False
    try:
        salt = base64.b64decode(ADMIN_PASSWORD_SALT_B64)
        expected = base64.b64decode(ADMIN_PASSWORD_HASH_B64)
    except Exception:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 210000, dklen=32)
    return hmac.compare_digest(actual, expected)


def get_db():
    return get_wa_agent_db()


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


SUSU_SETTINGS_TABLE = "wa_susu_settings"
SUSU_SETTING_SPECS = {
    "system_persona": {"type": "multiline", "max_length": 12000, "default": SYSTEM_PERSONA, "required": True},
    "primary_user_memory": {"type": "multiline", "max_length": 12000, "default": PRIMARY_USER_MEMORY, "required": False},
    "relay_model": {"type": "text", "max_length": 120, "default": RELAY_MODEL, "required": True},
    "relay_fallback_model": {"type": "text", "max_length": 120, "default": RELAY_FALLBACK_MODEL, "required": False},
    "gemini_model": {"type": "text", "max_length": 120, "default": GEMINI_MODEL, "required": True},
    "proactive_enabled": {"type": "bool", "default": PROACTIVE_ENABLED},
    "proactive_scan_seconds": {"type": "int", "default": PROACTIVE_SCAN_SECONDS, "min": 60, "max": 3600},
    "proactive_min_silence_minutes": {"type": "int", "default": PROACTIVE_MIN_SILENCE_MINUTES, "min": 5, "max": 1440},
    "proactive_cooldown_minutes": {"type": "int", "default": PROACTIVE_COOLDOWN_MINUTES, "min": 10, "max": 2880},
    "proactive_reply_window_minutes": {"type": "int", "default": PROACTIVE_REPLY_WINDOW_MINUTES, "min": 10, "max": 1440},
    "proactive_conversation_window_hours": {"type": "int", "default": PROACTIVE_CONVERSATION_WINDOW_HOURS, "min": 1, "max": 168},
    "proactive_max_per_service_day": {"type": "int", "default": PROACTIVE_MAX_PER_SERVICE_DAY, "min": 0, "max": 20},
    "proactive_min_inbound_messages": {"type": "int", "default": PROACTIVE_MIN_INBOUND_MESSAGES, "min": 1, "max": 200},
}


def normalize_susu_multiline(value, fallback=""):
    text = str(fallback if value is None else value).replace("\r\n", "\n").replace("\r", "\n").strip()
    return re.sub(r"\n{3,}", "\n\n", text)


def normalize_susu_text(value, fallback=""):
    return re.sub(r"\s+", " ", str(fallback if value is None else value).strip())


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
    conn = get_db()
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


def dedupe_primary_long_term_memories(wa_id=""):
    wa_id = susu_clean_text(wa_id or ADMIN_WA_ID)
    if not wa_id:
        return {"ok": False, "detail": "Missing wa_id"}
    conn = get_db()
    try:
        settings = fetch_susu_settings_with_conn(conn)["values"]
        primary_lines = split_susu_memory_lines(settings.get("primary_user_memory", ""))
        if not primary_lines:
            return {"ok": True, "wa_id": wa_id, "removed_count": 0, "removed_items": []}
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
        return {"ok": True, "wa_id": wa_id, "removed_count": len(removed_ids), "removed_items": removed_items[:20]}
    finally:
        conn.close()


def wa_table_exists(conn, table_name):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return bool(row)


def fetch_susu_contacts(conn):
    contacts = {}
    archive_enabled = wa_table_exists(conn, "wa_memory_archive")
    for row in conn.execute(
        """
        SELECT wa_id, profile_name, updated_at
        FROM wa_contacts
        ORDER BY updated_at DESC, wa_id ASC
        """
    ).fetchall():
        wa_id = row["wa_id"]
        contacts[wa_id] = {
            "wa_id": wa_id,
            "profile_name": row["profile_name"] or "",
            "updated_at": row["updated_at"] or "",
        }

    table_names = ["wa_memories", "wa_session_memories", "wa_reminders"]
    if archive_enabled:
        table_names.append("wa_memory_archive")
    for table_name in table_names:
        rows = conn.execute(f"SELECT DISTINCT wa_id FROM {table_name} ORDER BY wa_id ASC").fetchall()
        for row in rows:
            wa_id = row["wa_id"]
            contacts.setdefault(
                wa_id,
                {"wa_id": wa_id, "profile_name": "", "updated_at": ""},
            )

    ranked = []
    for item in contacts.values():
        wa_id = item["wa_id"]
        archive_count = 0
        if archive_enabled:
            archive_count = int(
                conn.execute(
                    "SELECT COUNT(*) AS total FROM wa_memory_archive WHERE wa_id = ?",
                    (wa_id,),
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
            (wa_id, wa_id, wa_id, wa_id),
        ).fetchone()
        ranked.append(
            {
                **item,
                "display_name": item["profile_name"] or wa_id,
                "memory_count": int(counts["memory_count"]),
                "session_count": int(counts["session_count"]),
                "archive_count": archive_count,
                "reminder_count": int(counts["reminder_count"]),
                "pending_reminder_count": int(counts["pending_reminder_count"]),
            }
        )

    ranked.sort(
        key=lambda item: (
            -(item["memory_count"] + item["session_count"] + item["archive_count"] + item["reminder_count"]),
            item["display_name"].lower(),
            item["wa_id"],
        )
    )
    return ranked


def fetch_susu_memory(selected_wa_id=""):
    conn = get_db()
    try:
        archive_enabled = wa_table_exists(conn, "wa_memory_archive")
        contacts = fetch_susu_contacts(conn)
        wa_ids = {item["wa_id"] for item in contacts}
        if selected_wa_id not in wa_ids:
            selected_wa_id = contacts[0]["wa_id"] if contacts else ""

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
                bucket = current_session_bucket(observed_at, now_utc) or (row["bucket"] or "within_7d")
                session_memories.append(
                    {
                        "id": row["id"],
                        "wa_id": row["wa_id"],
                        "bucket": bucket,
                        "bucket_label": SESSION_BUCKET_LABELS.get(bucket, bucket),
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
                        "source_bucket_label": SESSION_BUCKET_LABELS.get(
                            row["source_bucket"] or "within_7d",
                            row["source_bucket"] or "within_7d",
                        ),
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
            "db_path": str(DB_PATH),
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
    wa_id = susu_clean_text(wa_id)
    content = susu_clean_text(content)
    kind = susu_clean_text(kind)[:40] or "manual"
    if not wa_id or not content:
        return {"ok": False, "detail": "Missing wa_id or content"}
    memory_key = susu_normalize_key(content)
    if not memory_key:
        return {"ok": False, "detail": "Invalid content"}

    now = utc_now()
    conn = get_db()
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


def update_susu_memory(entry_id, content, kind=""):
    entry_id = int(entry_id or 0)
    content = susu_clean_text(content)
    if not entry_id or not content:
        return {"ok": False, "detail": "Missing id or content"}

    conn = get_db()
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
            conn.execute(
                """
                UPDATE wa_memories
                SET kind = ?, content = ?, updated_at = ?
                WHERE id = ?
                """,
                (next_kind, content, now, duplicate["id"]),
            )
            conn.execute("DELETE FROM wa_memories WHERE id = ?", (entry_id,))
            target_id = duplicate["id"]
        else:
            conn.execute(
                """
                UPDATE wa_memories
                SET kind = ?, content = ?, memory_key = ?, updated_at = ?
                WHERE id = ?
                """,
                (next_kind, content, next_key, now, entry_id),
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

    conn = get_db()
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
            (parsed.isoformat(), content, entry_id),
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

    conn = get_db()
    try:
        result = conn.execute(f"DELETE FROM {table_name} WHERE id = ?", (entry_id,))
        conn.commit()
        return {"ok": result.rowcount > 0}
    finally:
        conn.close()


class Handler(BaseHTTPRequestHandler):
    def _send_bytes(self, payload, status=200, content_type="application/octet-stream", extra_headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        if extra_headers:
            for header_name, header_value in extra_headers:
                self.send_header(header_name, header_value)
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, data, status=200, extra_headers=None):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self._send_bytes(body, status, "application/json; charset=utf-8", extra_headers)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return None

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Allow", "GET, POST, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path in {"", "/", "/index.html", "/susu-memory-admin.html"}:
            if not ADMIN_UI_PATH.exists():
                self._send_json({"error": "Admin UI not found"}, 500)
                return
            self._send_bytes(
                ADMIN_UI_PATH.read_bytes(),
                200,
                "text/html; charset=utf-8",
            )
            return

        if parsed.path == "/healthz":
            self._send_json(
                {
                    "ok": True,
                    "db_path": str(DB_PATH),
                    "admin_ui": str(ADMIN_UI_PATH),
                    "admin_login_ready": admin_login_ready(),
                }
            )
            return

        if parsed.path == "/api/admin/status":
            self._send_json(
                {
                    "authenticated": is_admin_authenticated(self),
                    "configured": admin_login_ready(),
                    "display_name": ADMIN_NAME,
                }
            )
            return

        if parsed.path == "/api/admin/susu-memory":
            if not is_admin_authenticated(self):
                self._send_json({"error": "Forbidden"}, 403)
                return
            try:
                qs = parse_qs(parsed.query)
                selected_wa_id = qs.get("wa_id", [""])[0].strip()
                self._send_json(fetch_susu_memory(selected_wa_id))
            except Exception as exc:
                self._send_json({"error": str(exc)}, 500)
            return

        self._send_json({"error": "Not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        data = self._read_json()
        if data is None:
            self._send_json({"error": "Invalid JSON"}, 400)
            return

        if parsed.path == "/api/admin/login":
            if not admin_login_ready():
                self._send_json({"error": "Admin auth not configured"}, 503)
                return
            password = str(data.get("password", ""))
            if not verify_admin_password(password):
                self._send_json({"error": "Invalid password"}, 403)
                return
            self._send_json(
                {"authenticated": True, "display_name": ADMIN_NAME},
                extra_headers=[("Set-Cookie", make_admin_session_cookie())],
            )
            return

        if parsed.path == "/api/admin/logout":
            self._send_json(
                {"authenticated": False},
                extra_headers=[("Set-Cookie", clear_admin_session_cookie())],
            )
            return

        if not is_admin_authenticated(self):
            self._send_json({"error": "Forbidden"}, 403)
            return

        if parsed.path == "/api/admin/susu-memory/update":
            entry_id = str(data.get("id", "")).strip()
            item_type = str(data.get("type", "memory")).strip()
            content = str(data.get("content", data.get("value", "")))
            kind = str(data.get("kind", "")).strip()
            remind_at = str(data.get("remind_at", "")).strip()
            if not entry_id:
                self._send_json({"error": "Missing id"}, 400)
                return
            try:
                if item_type == "reminder":
                    result = update_susu_reminder(entry_id, remind_at, content)
                else:
                    result = update_susu_memory(entry_id, content, kind)
            except Exception as exc:
                result = {"ok": False, "detail": str(exc)}
            self._send_json(result, 200 if result.get("ok") else 400)
            return

        if parsed.path == "/api/admin/susu-memory/delete":
            entry_id = str(data.get("id", "")).strip()
            item_type = str(data.get("type", "memory")).strip()
            if not entry_id:
                self._send_json({"error": "Missing id"}, 400)
                return
            try:
                result = delete_susu_memory(entry_id, item_type)
            except Exception as exc:
                result = {"ok": False, "detail": str(exc)}
            self._send_json(result, 200 if result.get("ok") else 400)
            return

        if parsed.path == "/api/admin/susu-memory/create":
            kind = str(data.get("kind", data.get("key", "manual"))).strip()
            content = str(data.get("content", data.get("value", ""))).strip()
            wa_id = str(data.get("wa_id", data.get("userId", ""))).strip()
            if not kind or not content or not wa_id:
                self._send_json({"error": "Missing kind, content or wa_id"}, 400)
                return
            try:
                result = create_susu_memory(wa_id, content, kind)
            except Exception as exc:
                result = {"ok": False, "detail": str(exc)}
            self._send_json(result, 200 if result.get("ok") else 400)
            return

        if parsed.path == "/api/admin/susu-settings/update":
            changes = data.get("settings")
            try:
                result = update_susu_settings(changes)
            except Exception as exc:
                result = {"ok": False, "detail": str(exc)}
            self._send_json(result, 200 if result.get("ok") else 400)
            return

        if parsed.path == "/api/admin/susu-memory/deduplicate":
            wa_id = str(data.get("wa_id", "")).strip()
            try:
                result = dedupe_primary_long_term_memories(wa_id)
            except Exception as exc:
                result = {"ok": False, "detail": str(exc)}
            self._send_json(result, 200 if result.get("ok") else 400)
            return

        self._send_json({"error": "Not found"}, 404)


if __name__ == "__main__":
    server = ThreadingHTTPServer((ADMIN_HOST, ADMIN_PORT), Handler)
    server.serve_forever()
