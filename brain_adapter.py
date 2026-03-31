#!/usr/bin/env python3
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class BrainBridgeError(RuntimeError):
    pass


def _extract_message_text(payload):
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices") or []
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message") or {}
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            chunks = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text = str(item.get("text", "")).strip()
                    if text:
                        chunks.append(text)
            if chunks:
                return "\n".join(chunks).strip()
        text = choice.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
    data = payload.get("data")
    if isinstance(data, dict):
        return _extract_message_text(data)
    return ""


def call_brain_bridge(api_url, api_key, payload, timeout=90):
    if not api_url:
        raise BrainBridgeError("missing_brain_bridge_url")

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    request = Request(
        api_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="ignore")
        except Exception:
            detail = ""
        suffix = f":{detail[:240]}" if detail else ""
        raise BrainBridgeError(f"http_{exc.code}{suffix}") from exc
    except URLError as exc:
        raise BrainBridgeError(f"url_error:{exc.reason}") from exc
    except Exception as exc:
        raise BrainBridgeError(f"request_failed:{type(exc).__name__}") from exc

    try:
        data = json.loads(raw or "{}")
    except Exception as exc:
        raise BrainBridgeError(f"invalid_json:{exc}") from exc

    text = _extract_message_text(data)
    if not text:
        raise BrainBridgeError("empty_response")
    return text
