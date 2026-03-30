#!/usr/bin/env python3
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from agnai_backend_adapter import (
    AgnaiBackendAdapterError,
    build_backend_brain_payload,
    call_brain_backend,
    normalize_brain_reply,
)


BRIDGE_HOST = os.environ.get("WA_ST_BRIDGE_HOST", "127.0.0.1").strip() or "127.0.0.1"
BRIDGE_PORT = int(os.environ.get("WA_ST_BRIDGE_PORT", "9102"))
BRIDGE_API_KEY = os.environ.get("WA_ST_BRIDGE_API_KEY", "").strip()
UPSTREAM_MODE = os.environ.get("WA_ST_BRIDGE_UPSTREAM_MODE", "openai").strip().lower() or "openai"
UPSTREAM_URL = os.environ.get("WA_ST_BRIDGE_UPSTREAM_URL", "").strip()
UPSTREAM_API_KEY = os.environ.get("WA_ST_BRIDGE_UPSTREAM_API_KEY", "").strip()
UPSTREAM_MODEL = os.environ.get("WA_ST_BRIDGE_UPSTREAM_MODEL", "").strip()
UPSTREAM_TIMEOUT_SECONDS = float(os.environ.get("WA_ST_BRIDGE_TIMEOUT_SECONDS", "90"))
UPSTREAM_AUTH_HEADER = os.environ.get("WA_ST_BRIDGE_UPSTREAM_AUTH_HEADER", "Authorization").strip() or "Authorization"


def utc_unix():
    return int(time.time())


def json_bytes(payload):
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def build_error(message, code="bridge_error", status=500, detail=""):
    body = {
        "error": {
            "message": message,
            "type": code,
            "detail": detail[:400],
        }
    }
    return status, body


def extract_bearer_token(handler):
    header = handler.headers.get("Authorization", "")
    if not header.lower().startswith("bearer "):
        return ""
    return header.split(" ", 1)[1].strip()


def bridge_auth_ok(handler):
    if not BRIDGE_API_KEY:
        return True
    return extract_bearer_token(handler) == BRIDGE_API_KEY


def read_json_body(handler):
    content_length = int(handler.headers.get("Content-Length", "0") or "0")
    if content_length <= 0:
        raise ValueError("empty_body")
    raw = handler.rfile.read(content_length)
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"invalid_json:{exc}") from exc


def normalize_chat_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError("payload_must_be_object")
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("missing_messages")
    normalized = {
        "messages": messages,
        "temperature": payload.get("temperature", 0.8),
        "max_tokens": payload.get("max_tokens", 220),
        "stream": False,
    }
    model_name = str(payload.get("model") or UPSTREAM_MODEL or "").strip()
    if model_name:
        normalized["model"] = model_name
    return normalized


def upstream_headers():
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if UPSTREAM_API_KEY:
        if UPSTREAM_AUTH_HEADER.lower() == "authorization":
            headers["Authorization"] = f"Bearer {UPSTREAM_API_KEY}"
        else:
            headers[UPSTREAM_AUTH_HEADER] = UPSTREAM_API_KEY
    return headers


def call_upstream(payload):
    if not UPSTREAM_URL:
        raise RuntimeError("missing_upstream_url")
    request = Request(
        UPSTREAM_URL,
        data=json_bytes(payload),
        headers=upstream_headers(),
        method="POST",
    )
    try:
        with urlopen(request, timeout=max(UPSTREAM_TIMEOUT_SECONDS, 5.0)) as response:
            raw = response.read().decode("utf-8")
            status = getattr(response, "status", 200) or 200
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="ignore")
        except Exception:
            detail = ""
        raise RuntimeError(f"http_{exc.code}:{detail[:300]}") from exc
    except URLError as exc:
        raise RuntimeError(f"url_error:{exc.reason}") from exc
    except Exception as exc:
        raise RuntimeError(f"request_failed:{type(exc).__name__}:{exc}") from exc
    try:
        data = json.loads(raw or "{}")
    except Exception as exc:
        raise RuntimeError(f"invalid_upstream_json:{exc}") from exc
    return status, data


def ensure_openai_shape(payload):
    if isinstance(payload, dict) and isinstance(payload.get("choices"), list):
        return payload
    text = ""
    if isinstance(payload, dict):
        text = str(payload.get("text") or payload.get("reply") or "").strip()
        if not text:
            data = payload.get("data")
            if isinstance(data, dict):
                text = str(data.get("text") or data.get("reply") or "").strip()
    if text:
        return {
            "id": f"chatcmpl-{utc_unix()}",
            "object": "chat.completion",
            "created": utc_unix(),
            "model": UPSTREAM_MODEL or "bridge-upstream",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
        }
    raise RuntimeError("upstream_missing_choices")


def dispatch_upstream(request_payload):
    mode = UPSTREAM_MODE.strip().lower()
    if mode in {"openai", "chatbridge", "sillytavern", ""}:
        upstream_payload = normalize_chat_payload(request_payload)
        _, upstream_response = call_upstream(upstream_payload)
        return ensure_openai_shape(upstream_response)
    if mode in {"agnai", "agnai_style", "susu_brain"}:
        brain_payload = build_backend_brain_payload(request_payload)
        brain_response = call_brain_backend(
            UPSTREAM_URL,
            brain_payload,
            api_key=UPSTREAM_API_KEY,
            timeout=UPSTREAM_TIMEOUT_SECONDS,
            auth_header=UPSTREAM_AUTH_HEADER,
        )
        return normalize_brain_reply(brain_response, default_model=UPSTREAM_MODEL or "agnai-style-backend")
    raise RuntimeError(f"unsupported_upstream_mode:{UPSTREAM_MODE}")


class BridgeHandler(BaseHTTPRequestHandler):
    server_version = "SusuBrainBridge/0.2"

    def _send_json(self, status, payload):
        body = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return

    def do_GET(self):
        if self.path.rstrip("/") == "/health":
            self._send_json(
                200,
                {
                    "ok": True,
                    "service": "susu_brain_bridge",
                    "upstream_mode": UPSTREAM_MODE,
                    "has_bridge_api_key": bool(BRIDGE_API_KEY),
                    "has_upstream_url": bool(UPSTREAM_URL),
                    "has_upstream_api_key": bool(UPSTREAM_API_KEY),
                    "upstream_model": UPSTREAM_MODEL,
                },
            )
            return
        self._send_json(404, {"error": {"message": "not_found"}})

    def do_POST(self):
        if self.path not in ("/v1/chat/completions", "/chat/completions"):
            self._send_json(404, {"error": {"message": "not_found"}})
            return
        if not bridge_auth_ok(self):
            status, payload = build_error("unauthorized", code="unauthorized", status=401)
            self._send_json(status, payload)
            return
        try:
            request_payload = read_json_body(self)
            response_payload = dispatch_upstream(request_payload)
            self._send_json(200, response_payload)
        except ValueError as exc:
            status, payload = build_error("bad_request", code="bad_request", status=400, detail=str(exc))
            self._send_json(status, payload)
        except AgnaiBackendAdapterError as exc:
            status, payload = build_error("upstream_failed", code="upstream_failed", status=502, detail=str(exc))
            self._send_json(status, payload)
        except Exception as exc:
            status, payload = build_error("upstream_failed", code="upstream_failed", status=502, detail=str(exc))
            self._send_json(status, payload)


def main():
    server = ThreadingHTTPServer((BRIDGE_HOST, BRIDGE_PORT), BridgeHandler)
    print(f"Susu brain bridge listening on http://{BRIDGE_HOST}:{BRIDGE_PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
