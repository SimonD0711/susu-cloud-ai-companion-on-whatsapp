"""Reminder detection, parsing, and firing pipeline."""

from __future__ import annotations

import json
import re as re_module
from datetime import datetime, timezone
from typing import Optional, Tuple

from src.wa_agent.whatsapp import send_whatsapp_text


def hk_now() -> datetime:
    """Return current time in Hong Kong timezone."""
    return datetime.now(timezone.utc).astimezone()


def utc_now() -> str:
    """Return current UTC time as ISO string."""
    return datetime.now(timezone.utc).isoformat()


def _generate_model_text(prompt: str, temperature: float = 0.0, max_tokens: int = 80) -> str:
    """Generate text using the relay LLM. Import from wa_agent at call time."""
    import sys
    from pathlib import Path
    wa_path = str(Path(__file__).resolve().parent.parent.parent)
    if wa_path not in sys.path:
        sys.path.insert(0, wa_path)
    from wa_agent import generate_model_text
    return generate_model_text(prompt, temperature=temperature, max_tokens=max_tokens)


def _is_reminder_task(text: str) -> bool:
    """Check if text is a reminder/task setting request using AI."""
    prompt = f"""判斷以下訊息係咪設定提醒嘅請求（例如「6點提醒我開會」「remind me at 9am」）。
    只回答 YES 或 NO。
    訊息：{text}""".strip()
    try:
        result = _generate_model_text(prompt, temperature=0.0, max_tokens=5)
        return (result or "").strip().upper().startswith("Y")
    except Exception:
        return False


def _parse_reminder(wa_id: str, text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Parse a reminder from natural language text.
    
    Returns:
        Tuple of (remind_at_iso, content) or (None, None) if parsing fails.
    """
    now = hk_now()
    prompt = f"""現在時間係 {now.strftime('%Y-%m-%d %H:%M')} HKT。
    用戶訊息：{text}

    提取提醒時間和內容，以 JSON 格式輸出：
    {{"remind_at": "YYYY-MM-DDTHH:MM:00+08:00", "content": "提醒內容"}}
    如果無法提取，輸出 {{"remind_at": null, "content": null}}
    只輸出 JSON。""".strip()
    try:
        raw = _generate_model_text(prompt, temperature=0.0, max_tokens=80)
        m = re_module.search(r'\{.*\}', raw, re_module.DOTALL)
        if not m:
            return None, None
        data = json.loads(m.group())
        return data.get("remind_at"), data.get("content")
    except Exception:
        return None, None


def detect_reminder(text: str) -> bool:
    """Detect if a message is a reminder request (AI-based)."""
    return _is_reminder_task(text)


def parse_reminder_from_text(wa_id: str, text: str) -> Tuple[Optional[str], Optional[str]]:
    """Parse reminder time and content from user text."""
    return _parse_reminder(wa_id, text)


def fire_reminder(wa_id: str, content: str) -> bool:
    """
    Fire a reminder by generating a friendly message and sending via WhatsApp.
    
    Args:
        wa_id: WhatsApp recipient ID
        content: Reminder content
    
    Returns:
        True if sent successfully, False otherwise.
    """
    prompt = f"你係苏苏，用戶設定咗一個提醒：{content}。而家時間到咗，用一句自然香港女仔口吻提醒用戶，要有少少甜味。只輸出那句話。"
    try:
        msg = _generate_model_text(prompt, temperature=0.85, max_tokens=60) or f"記住喇～ {content} 啊！"
    except Exception:
        msg = f"記住喇～ {content} 啊！"

    result = send_whatsapp_text(wa_id, msg)
    return bool(result.get("messages") and result["messages"][0].get("id"))


def run_reminder_scan_once() -> dict:
    """
    Scan for due reminders and fire them.
    
    Returns:
        Dict with status information.
    """
    try:
        from src.wa_agent.db import MemoryDB
        db = MemoryDB()
        conn = db.get_connection()
        now_iso = hk_now().isoformat()
        rows = db.get_pending_reminders(wa_id=None, now_iso=now_iso)
        all_wa_ids = {row["wa_id"] for row in conn.execute(
            "SELECT DISTINCT wa_id FROM wa_reminders WHERE fired = 0 AND remind_at <= ?",
            (now_iso,),
        ).fetchall()}
        for wa_id in all_wa_ids:
            reminders = db.get_pending_reminders(wa_id=wa_id, now_iso=now_iso)
            for row in reminders:
                try:
                    fire_reminder(row["wa_id"], row["content"])
                    db.mark_reminder_fired(row["id"])
                    db.commit()
                except Exception:
                    pass
        db.close()
        return {"ok": True, "status": "scanned"}
    except Exception:
        return {"ok": False, "status": "error"}


def reminder_loop() -> None:
    """Infinite loop that periodically scans for due reminders."""
    import time
    while True:
        try:
            run_reminder_scan_once()
        except Exception:
            pass
        time.sleep(60)
