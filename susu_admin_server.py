#!/usr/bin/env python3
import base64
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

from wa_agent import DB_PATH, get_db as get_wa_agent_db, utc_now


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

        self._send_json({"error": "Not found"}, 404)


if __name__ == "__main__":
    server = ThreadingHTTPServer((ADMIN_HOST, ADMIN_PORT), Handler)
    server.serve_forever()
