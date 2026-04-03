#!/usr/bin/env python3
import base64
import hashlib
import hmac
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from susu_admin_core import (
    SUSU_PRIMARY_WA_ID,
    create_susu_memory,
    dedupe_primary_long_term_memories,
    delete_susu_memory,
    fetch_susu_memory,
    promote_archive_memory,
    renew_session_memory,
    update_susu_memory,
    update_susu_reminder,
    update_susu_settings,
)


ADMIN_HOST = os.environ.get("SUSU_ADMIN_HOST", "127.0.0.1").strip() or "127.0.0.1"
ADMIN_PORT = int(os.environ.get("SUSU_ADMIN_PORT", "9001"))
API_PREFIX = "/api/susu-admin"
ADMIN_NAME = os.environ.get("SUSU_ADMIN_DISPLAY_NAME", "Admin").strip() or "Admin"
ADMIN_PASSWORD_SALT_B64 = os.environ.get("SUSU_ADMIN_PASSWORD_SALT_B64", "").strip()
ADMIN_PASSWORD_HASH_B64 = os.environ.get("SUSU_ADMIN_PASSWORD_HASH_B64", "").strip()
ADMIN_SESSION_SECRET = os.environ.get("SUSU_ADMIN_SESSION_SECRET", "").strip()
ADMIN_SESSION_COOKIE = os.environ.get("SUSU_ADMIN_SESSION_COOKIE", "susu_admin_session").strip() or "susu_admin_session"
ADMIN_SESSION_TTL = int(os.environ.get("SUSU_ADMIN_SESSION_TTL", str(60 * 60 * 24 * 30)))


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
        ADMIN_PASSWORD_SALT_B64
        and ADMIN_PASSWORD_HASH_B64
        and ADMIN_SESSION_SECRET
    )


def sign_admin_session(expires_at):
    message = f"admin|{expires_at}".encode("utf-8")
    return hmac.new(ADMIN_SESSION_SECRET.encode("utf-8"), message, hashlib.sha256).hexdigest()


def make_admin_session_cookie():
    expires_at = int(time.time()) + ADMIN_SESSION_TTL
    signature = sign_admin_session(expires_at)
    token = base64.urlsafe_b64encode(f"{expires_at}:{signature}".encode("utf-8")).decode("ascii")
    return f"{ADMIN_SESSION_COOKIE}={token}; Max-Age={ADMIN_SESSION_TTL}; Path=/; HttpOnly; SameSite=Lax"


def clear_admin_session_cookie():
    return f"{ADMIN_SESSION_COOKIE}=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax"


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
    salt = base64.b64decode(ADMIN_PASSWORD_SALT_B64)
    expected = base64.b64decode(ADMIN_PASSWORD_HASH_B64)
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 210000, dklen=32)
    return hmac.compare_digest(actual, expected)


class Handler(BaseHTTPRequestHandler):
    server_version = "SusuAdminServer/0.1"

    def log_message(self, format, *args):
        return

    def _send_json(self, payload, status=200, extra_headers=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if extra_headers:
            for key, value in extra_headers:
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
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

        if parsed.path == "/healthz":
            self._send_json(
                {
                    "ok": True,
                    "service": "susu_admin_api",
                    "api_prefix": API_PREFIX,
                    "admin_login_ready": admin_login_ready(),
                }
            )
            return

        if parsed.path == f"{API_PREFIX}/status":
            self._send_json(
                {
                    "authenticated": is_admin_authenticated(self),
                    "configured": admin_login_ready(),
                    "display_name": ADMIN_NAME,
                }
            )
            return

        if parsed.path == f"{API_PREFIX}/memory":
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

        if parsed.path == f"{API_PREFIX}/login":
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

        if parsed.path == f"{API_PREFIX}/logout":
            self._send_json(
                {"authenticated": False},
                extra_headers=[("Set-Cookie", clear_admin_session_cookie())],
            )
            return

        if not is_admin_authenticated(self):
            self._send_json({"error": "Forbidden"}, 403)
            return

        if parsed.path == f"{API_PREFIX}/memory/update":
            entry_id = str(data.get("id", "")).strip()
            item_type = str(data.get("type", "memory")).strip()
            content = str(data.get("content", data.get("value", "")))
            kind = str(data.get("kind", "")).strip()
            remind_at = str(data.get("remind_at", "")).strip()
            importance_raw = data.get("importance")
            if importance_raw is not None:
                try:
                    importance = int(importance_raw)
                except (ValueError, TypeError):
                    importance = None
            else:
                importance = None
            if not entry_id:
                self._send_json({"error": "Missing id"}, 400)
                return
            try:
                if item_type == "reminder":
                    result = update_susu_reminder(entry_id, remind_at, content)
                else:
                    result = update_susu_memory(entry_id, content, kind, importance)
            except Exception as exc:
                result = {"ok": False, "detail": str(exc)}
            self._send_json(result, 200 if result.get("ok") else 400)
            return

        if parsed.path == f"{API_PREFIX}/memory/delete":
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

        if parsed.path == f"{API_PREFIX}/memory/create":
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

        if parsed.path == f"{API_PREFIX}/settings/update":
            changes = data.get("settings")
            try:
                result = update_susu_settings(changes)
            except Exception as exc:
                result = {"ok": False, "detail": str(exc)}
            self._send_json(result, 200 if result.get("ok") else 400)
            return

        if parsed.path == f"{API_PREFIX}/memory/deduplicate":
            wa_id = str(data.get("wa_id", "")).strip()
            try:
                result = dedupe_primary_long_term_memories(wa_id or SUSU_PRIMARY_WA_ID)
            except Exception as exc:
                result = {"ok": False, "detail": str(exc)}
            self._send_json(result, 200 if result.get("ok") else 400)
            return

        if parsed.path == f"{API_PREFIX}/memory/renew-session":
            entry_id = str(data.get("id", "")).strip()
            days = int(data.get("days", 7))
            if not entry_id:
                self._send_json({"error": "Missing id"}, 400)
                return
            try:
                result = renew_session_memory(entry_id, days)
            except Exception as exc:
                result = {"ok": False, "detail": str(exc)}
            self._send_json(result, 200 if result.get("ok") else 400)
            return

        if parsed.path == f"{API_PREFIX}/memory/promote-archive":
            entry_id = str(data.get("id", "")).strip()
            if not entry_id:
                self._send_json({"error": "Missing id"}, 400)
                return
            try:
                result = promote_archive_memory(entry_id)
            except Exception as exc:
                result = {"ok": False, "detail": str(exc)}
            self._send_json(result, 200 if result.get("ok") else 400)
            return

        self._send_json({"error": "Not found"}, 404)


if __name__ == "__main__":
    server = ThreadingHTTPServer((ADMIN_HOST, ADMIN_PORT), Handler)
    server.serve_forever()
