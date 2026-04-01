"""WhatsApp Business API wrapper — send messages, media, status updates."""

from __future__ import annotations

import json
import os
import subprocess
import time as time_module
from datetime import datetime, timezone
from typing import Optional
from urllib.request import Request, urlopen


GRAPH_VERSION = os.environ.get("WA_GRAPH_VERSION", "v22.0")
ACCESS_TOKEN = os.environ.get("WA_ACCESS_TOKEN", "")
PHONE_NUMBER_ID = os.environ.get("WA_PHONE_NUMBER_ID", "")


def _graph_url(path: str) -> str:
    return f"https://graph.facebook.com/{GRAPH_VERSION}/{path.lstrip('/')}"


def _request(url: str, payload: dict, method: str = "POST", timeout: int = 20) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {ACCESS_TOKEN}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {"ok": True}


def send_whatsapp_text(to_number: str, body: str) -> dict:
    """Send a text message via WhatsApp Business API."""
    if not ACCESS_TOKEN or not PHONE_NUMBER_ID:
        return {"ok": False, "detail": "Missing WhatsApp credentials"}

    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": body[:4096],
        },
    }
    url = _graph_url(f"{PHONE_NUMBER_ID}/messages")
    data = _request(url, payload, timeout=20)
    if (data.get("messages") or [{}])[0].get("id", ""):
        reset_contact_read_cycle(to_number)
    return data


def send_whatsapp_status_update(message_id: str, typing: bool = False) -> dict:
    """Send a status update (mark as read / typing indicator)."""
    if not ACCESS_TOKEN or not PHONE_NUMBER_ID:
        return {"ok": False, "detail": "Missing WhatsApp credentials"}
    if not message_id:
        return {"ok": False, "detail": "Missing message_id"}

    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
    }
    if typing:
        payload["typing_indicator"] = {"type": "text"}

    url = _graph_url(f"{PHONE_NUMBER_ID}/messages")
    data = _request(url, payload, timeout=15)
    return data


def send_whatsapp_mark_as_read(message_id: str) -> dict:
    """Mark a message as read."""
    return send_whatsapp_status_update(message_id, typing=False)


def send_whatsapp_typing_indicator(message_id: str) -> dict:
    """Send a typing indicator."""
    return send_whatsapp_status_update(message_id, typing=True)


def upload_whatsapp_media(file_path: str, mime_type: str = "audio/mpeg") -> Optional[str]:
    """Upload a media file and return the media ID."""
    if not os.path.exists(file_path):
        return None
    if not ACCESS_TOKEN or not PHONE_NUMBER_ID:
        return None

    with open(file_path, "rb") as f:
        file_data = f.read()

    boundary = "WaAgentBoundary" + str(int(datetime.now(timezone.utc).timestamp() * 1000))
    body = b""
    body += (f"--{boundary}\r\n").encode()
    body += b'Content-Disposition: form-data; name="messaging_product"\r\n\r\n'
    body += b"whatsapp\r\n"
    body += (f"--{boundary}\r\n").encode()
    body += f'Content-Disposition: form-data; name="file"; filename="{os.path.basename(file_path)}"\r\n'.encode()
    body += f"Content-Type: {mime_type}\r\n\r\n".encode()
    body += file_data
    body += f"\r\n--{boundary}--\r\n".encode()

    try:
        req = Request(
            _graph_url(f"{PHONE_NUMBER_ID}/media"),
            data=body,
            headers={
                "Authorization": f"Bearer {ACCESS_TOKEN}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST",
        )
        with urlopen(req, timeout=30) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        return raw.get("id")
    except Exception:
        return None


def send_whatsapp_audio(to_number: str, media_id: str) -> dict:
    """Send an audio message via WhatsApp Business API."""
    if not ACCESS_TOKEN or not PHONE_NUMBER_ID or not media_id:
        return {"ok": False}
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "audio",
        "audio": {"id": media_id},
    }
    try:
        url = _graph_url(f"{PHONE_NUMBER_ID}/messages")
        req = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return {"ok": False}


def send_whatsapp_reaction(to_number: str, message_id: str, emoji: str) -> dict:
    """Send an emoji reaction to a message."""
    if not ACCESS_TOKEN or not PHONE_NUMBER_ID:
        return {"ok": False}
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_number,
        "type": "reaction",
        "reaction": {"message_id": message_id, "emoji": emoji},
    }
    result = subprocess.run(
        [
            "curl",
            "-s",
            "-X",
            "POST",
            _graph_url(f"{PHONE_NUMBER_ID}/messages"),
            "-H",
            f"Authorization: Bearer {ACCESS_TOKEN}",
            "-H",
            "Content-Type: application/json",
            "-d",
            json.dumps(payload),
        ],
        capture_output=True,
        text=True,
    )
    try:
        return json.loads(result.stdout) if result.stdout else {"ok": False}
    except Exception:
        return {"ok": False}


_read_scheduler_states: dict = {}
_read_scheduler_states_lock = __import__("threading").Lock()


def default_read_scheduler_state() -> dict:
    return {
        "delay_consumed": False,
        "pending_message_ids": [],
        "timer_running": False,
        "deadline_at": 0.0,
        "cycle_id": 0,
    }


def reset_contact_read_cycle(wa_id: str) -> None:
    """Reset the read-receipt cycle for a contact."""
    from .brain import clean_text

    wa_value = clean_text(wa_id)
    if not wa_value:
        return
    with _read_scheduler_states_lock:
        state = _read_scheduler_states.setdefault(wa_value, default_read_scheduler_state())
        state["delay_consumed"] = False
        state["pending_message_ids"] = []
        state["timer_running"] = False
        state["deadline_at"] = 0.0
        state["cycle_id"] = int(state.get("cycle_id", 0) or 0) + 1


def parse_message_context(raw_payload: dict | str) -> dict:
    """Extract quoted message context from a webhook payload."""
    from .brain import clean_text

    payload = {}
    if isinstance(raw_payload, dict):
        payload = raw_payload
    else:
        try:
            payload = json.loads(raw_payload or "{}")
        except Exception:
            payload = {}
    context = payload.get("context") if isinstance(payload, dict) else {}
    if not isinstance(context, dict):
        context = {}
    return {
        "quoted_message_id": clean_text(context.get("id") or context.get("message_id")),
        "quoted_from": clean_text(context.get("from")),
    }
