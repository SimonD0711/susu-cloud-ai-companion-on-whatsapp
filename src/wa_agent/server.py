"""HTTP server entry point for Susu Agent.

This module provides the main() function that starts the HTTP server
and background threads for proactive messaging and reminders.
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


PORT = 9100


class HealthHandler(BaseHTTPRequestHandler):
    """HTTP handler for health check and webhook endpoints."""

    def _send_json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass

    def do_GET(self):
        from urllib.parse import parse_qs, urlparse
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send_json({"ok": True})
            return
        if parsed.path == "/whatsapp/webhook":
            qs = parse_qs(parsed.query)
            mode = qs.get("hub.mode", [""])[0]
            token = qs.get("hub.verify_token", [""])[0]
            challenge = qs.get("hub.challenge", [""])[0]
            if mode == "subscribe" and token:
                raw = challenge.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                try:
                    self.wfile.write(raw)
                except BrokenPipeError:
                    pass
                return
            self._send_json({"error": "Forbidden"}, 403)
            return
        self._send_json({"error": "Not found"}, 404)


def main() -> None:
    """Start the HTTP server and background threads."""
    import os

    base_dir_env = os.environ.get("WA_BASE_DIR", "/var/www/html")
    base_dir = Path(base_dir_env)
    if not base_dir.exists():
        base_dir = Path(__file__).resolve().parent.parent.parent

    db_path_env = os.environ.get("WA_DB_PATH", "")
    if db_path_env:
        db_path = db_path_env
    else:
        db_path = str(base_dir / "wa_agent.db")

    try:
        import wa_agent
        bootstrap_conn = wa_agent.get_db()
        bootstrap_conn.close()
    except Exception:
        pass

    proactive_enabled = os.environ.get("WA_PROACTIVE_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
    if proactive_enabled:
        try:
            from src.wa_agent.proactive import proactive_loop
            threading.Thread(target=proactive_loop, name="wa-proactive-loop", daemon=True).start()
        except Exception:
            pass

    try:
        from src.wa_agent.reminders import reminder_loop
        threading.Thread(target=reminder_loop, name="wa-reminder-loop", daemon=True).start()
    except Exception:
        pass

    try:
        import wa_agent as agent_module
        if hasattr(agent_module, "pending_reply_recovery_loop"):
            threading.Thread(target=agent_module.pending_reply_recovery_loop, name="wa-reply-recovery-loop", daemon=True).start()
    except Exception:
        pass

    server_address = ("127.0.0.1", PORT)
    try:
        import wa_agent as agent_module
        HandlerClass = agent_module.Handler
    except Exception:
        HandlerClass = HealthHandler

    server = ThreadingHTTPServer(server_address, HandlerClass)
    print(f"Starting server on port {PORT}...")
    server.serve_forever()


if __name__ == "__main__":
    main()
