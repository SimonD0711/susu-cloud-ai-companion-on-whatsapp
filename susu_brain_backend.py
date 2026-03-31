#!/usr/bin/env python3
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BACKEND_HOST = os.environ.get("WA_SUSU_BRAIN_HOST", "127.0.0.1").strip() or "127.0.0.1"
BACKEND_PORT = int(os.environ.get("WA_SUSU_BRAIN_PORT", "9103"))
BACKEND_API_KEY = os.environ.get("WA_SUSU_BRAIN_API_KEY", "").strip()
BACKEND_TIMEOUT_SECONDS = float(os.environ.get("WA_SUSU_BRAIN_TIMEOUT_SECONDS", "90"))
RELAY_API_KEY = os.environ.get("WA_RELAY_API_KEY", "").strip()
RELAY_BASE_URL = os.environ.get("WA_RELAY_BASE_URL", "https://apiapipp.com/v1").strip() or "https://apiapipp.com/v1"
DEFAULT_MODEL = os.environ.get("WA_SUSU_BRAIN_MODEL", os.environ.get("WA_RELAY_MODEL", "claude-opus-4-6")).strip() or "claude-opus-4-6"
RELAY_RETRY_COUNT = int(os.environ.get("WA_RELAY_RETRY_COUNT", "2"))
RELAY_RETRY_BACKOFF_SECONDS = float(os.environ.get("WA_RELAY_RETRY_BACKOFF_SECONDS", "1.0"))


def json_bytes(payload):
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def utc_unix():
    return int(time.time())


def build_error(message, code="backend_error", status=500, detail=""):
    return status, {
        "error": {
            "message": message,
            "type": code,
            "detail": detail[:400],
        }
    }


def extract_bearer_token(handler):
    header = handler.headers.get("Authorization", "")
    if not header.lower().startswith("bearer "):
        return ""
    return header.split(" ", 1)[1].strip()


def backend_auth_ok(handler):
    if not BACKEND_API_KEY:
        return True
    return extract_bearer_token(handler) == BACKEND_API_KEY


def read_json_body(handler):
    content_length = int(handler.headers.get("Content-Length", "0") or "0")
    if content_length <= 0:
        raise ValueError("empty_body")
    raw = handler.rfile.read(content_length)
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"invalid_json:{exc}") from exc


def normalize_conversation(conversation):
    normalized = []
    for item in conversation or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower() or "user"
        content = item.get("content")
        if isinstance(content, list):
            chunks = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text = str(part.get("text") or "").strip()
                    if text:
                        chunks.append(text)
            content = "\n".join(chunks).strip()
        else:
            content = str(content or "").strip()
        if not content:
            continue
        normalized.append({"role": role, "content": content})
    return normalized


def build_openai_messages(payload):
    if not isinstance(payload, dict):
        raise ValueError("payload_must_be_object")
    system_prompt = str(payload.get("system_prompt") or "").strip()
    conversation = normalize_conversation(payload.get("conversation") or [])
    latest_user_message = str(payload.get("latest_user_message") or "").strip()
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.extend(conversation)
    if latest_user_message and (not conversation or conversation[-1].get("content") != latest_user_message):
        messages.append({"role": "user", "content": latest_user_message})
    if not messages:
        raise ValueError("missing_messages")
    return messages


def call_relay(messages, temperature=0.8, max_tokens=220, model_name=""):
    if not RELAY_API_KEY:
        raise RuntimeError("missing_relay_api_key")
    payload = {
        "model": model_name or DEFAULT_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    request = Request(
        f"{RELAY_BASE_URL.rstrip('/')}/chat/completions",
        data=json_bytes(payload),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {RELAY_API_KEY}",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=max(BACKEND_TIMEOUT_SECONDS, 5.0)) as response:
            raw = response.read().decode("utf-8")
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
        raise RuntimeError(f"invalid_relay_json:{exc}") from exc
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("missing_choices")
    message = (choices[0] or {}).get("message") or {}
    content = str(message.get("content") or "").strip()
    if not content:
        raise RuntimeError("empty_reply")
    return content


def should_retry_relay_exception(exc):
    if isinstance(exc, URLError):
        return True
    if isinstance(exc, HTTPError):
        return exc.code in (408, 409, 425, 429, 500, 502, 503, 504)
    detail = str(exc)
    return any(token in detail for token in ["http_502", "http_503", "http_504", "url_error"])


def call_relay_with_retry(messages, temperature=0.8, max_tokens=220, model_name=""):
    attempts = max(RELAY_RETRY_COUNT, 1)
    last_exc = None
    for attempt in range(attempts):
        try:
            return call_relay(messages, temperature=temperature, max_tokens=max_tokens, model_name=model_name)
        except Exception as exc:
            last_exc = exc
            if attempt >= attempts - 1 or not should_retry_relay_exception(exc):
                raise
            time.sleep(max(RELAY_RETRY_BACKOFF_SECONDS, 0.1) * (attempt + 1))
    if last_exc:
        raise last_exc
    raise RuntimeError("relay_failed_without_error")


class BrainHandler(BaseHTTPRequestHandler):
    server_version = "SusuBrainBackend/0.1"

    def log_message(self, format, *args):
        return

    def _send_json(self, status, payload):
        body = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/") == "/health":
            self._send_json(
                200,
                {
                    "ok": True,
                    "service": "susu_brain_backend",
                    "has_api_key": bool(BACKEND_API_KEY),
                    "has_relay_key": bool(RELAY_API_KEY),
                    "relay_base_url": RELAY_BASE_URL,
                    "default_model": DEFAULT_MODEL,
                },
            )
            return
        self._send_json(404, {"error": {"message": "not_found"}})

    def do_POST(self):
        if self.path not in ("/v1/agnai/chat", "/agnai/chat", "/v1/chat/completions"):
            self._send_json(404, {"error": {"message": "not_found"}})
            return
        if not backend_auth_ok(self):
            status, payload = build_error("unauthorized", code="unauthorized", status=401)
            self._send_json(status, payload)
            return
        try:
            request_payload = read_json_body(self)
            messages = build_openai_messages(request_payload)
            reply = call_relay_with_retry(
                messages,
                temperature=float(request_payload.get("temperature", 0.8)),
                max_tokens=int(request_payload.get("max_tokens", 220)),
                model_name=str(request_payload.get("model") or "").strip(),
            )
            self._send_json(
                200,
                {
                    "reply": reply,
                    "model": str(request_payload.get("model") or DEFAULT_MODEL).strip() or DEFAULT_MODEL,
                    "adapter": "agnai_style_v1",
                    "created": utc_unix(),
                },
            )
        except ValueError as exc:
            status, payload = build_error("bad_request", code="bad_request", status=400, detail=str(exc))
            self._send_json(status, payload)
        except Exception as exc:
            status, payload = build_error("backend_failed", code="backend_failed", status=502, detail=str(exc))
            self._send_json(status, payload)


def main():
    server = ThreadingHTTPServer((BACKEND_HOST, BACKEND_PORT), BrainHandler)
    print(f"Susu brain backend listening on http://{BACKEND_HOST}:{BACKEND_PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
