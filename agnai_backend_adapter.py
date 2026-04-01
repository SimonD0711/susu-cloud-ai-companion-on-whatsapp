#!/usr/bin/env python3
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class AgnaiBackendAdapterError(RuntimeError):
    pass


def _flatten_content(content):
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        chunks = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                text = str(item.get("text", "")).strip()
                if text:
                    chunks.append(text)
            elif item.get("type") == "image_url":
                chunks.append("[image attached]")
        return "\n".join(chunks).strip()
    return str(content or "").strip()


def _normalize_messages(messages):
    normalized = []
    for item in messages or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower() or "user"
        content = _flatten_content(item.get("content"))
        if not content:
            continue
        normalized.append({"role": role, "content": content})
    return normalized


def _extract_system_prompt(messages):
    system_parts = []
    conversation = []
    for item in messages:
        if item["role"] == "system":
            system_parts.append(item["content"])
        else:
            conversation.append(item)
    return "\n\n".join(part for part in system_parts if part).strip(), conversation


def _latest_user_message(messages):
    for item in reversed(messages):
        if item.get("role") == "user":
            return item.get("content", "")
    return ""


def build_backend_brain_payload(request_payload):
    if not isinstance(request_payload, dict):
        raise AgnaiBackendAdapterError("payload_must_be_object")
    normalized_messages = _normalize_messages(request_payload.get("messages") or [])
    if not normalized_messages:
        raise AgnaiBackendAdapterError("missing_messages")
    system_prompt, conversation = _extract_system_prompt(normalized_messages)
    payload = {
        "adapter": "agnai_style_v1",
        "kind": "susu_brain_request",
        "system_prompt": system_prompt,
        "conversation": conversation,
        "latest_user_message": _latest_user_message(conversation),
        "temperature": request_payload.get("temperature", 0.8),
        "max_tokens": request_payload.get("max_tokens", 220),
        "stream": False,
    }
    model_name = str(request_payload.get("model") or "").strip()
    if model_name:
        payload["model"] = model_name
    return payload


def _request_headers(api_key="", auth_header="Authorization"):
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if api_key:
        if (auth_header or "Authorization").lower() == "authorization":
            headers["Authorization"] = f"Bearer {api_key}"
        else:
            headers[auth_header] = api_key
    return headers


def call_brain_backend(api_url, payload, api_key="", timeout=90, auth_header="Authorization"):
    if not api_url:
        raise AgnaiBackendAdapterError("missing_backend_url")
    request = Request(
        api_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=_request_headers(api_key=api_key, auth_header=auth_header),
        method="POST",
    )
    try:
        with urlopen(request, timeout=max(float(timeout or 0), 5.0)) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="ignore")
        except Exception:
            detail = ""
        suffix = f":{detail[:320]}" if detail else ""
        raise AgnaiBackendAdapterError(f"http_{exc.code}{suffix}") from exc
    except URLError as exc:
        raise AgnaiBackendAdapterError(f"url_error:{exc.reason}") from exc
    except Exception as exc:
        raise AgnaiBackendAdapterError(f"request_failed:{type(exc).__name__}:{exc}") from exc
    try:
        return json.loads(raw or "{}")
    except Exception as exc:
        raise AgnaiBackendAdapterError(f"invalid_json:{exc}") from exc


def _extract_text(payload):
    if not isinstance(payload, dict):
        return ""
    reply = str(
        payload.get("text")
        or payload.get("reply")
        or payload.get("message")
        or payload.get("output")
        or ""
    ).strip()
    if reply:
        return reply
    choices = payload.get("choices") or []
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message") or {}
        content = _flatten_content(message.get("content"))
        if content:
            return content
        text = str(choice.get("text") or "").strip()
        if text:
            return text
    data = payload.get("data")
    if isinstance(data, dict):
        return _extract_text(data)
    response = payload.get("response")
    if isinstance(response, dict):
        return _extract_text(response)
    return ""


def normalize_brain_reply(payload, default_model="agnai-style-backend"):
    if isinstance(payload, dict) and isinstance(payload.get("choices"), list):
        return payload
    text = _extract_text(payload)
    if not text:
        raise AgnaiBackendAdapterError("empty_response")
    return {
        "id": "chatcmpl-agnai-bridge",
        "object": "chat.completion",
        "created": 0,
        "model": default_model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
    }
