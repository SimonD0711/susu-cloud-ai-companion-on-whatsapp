"""Proactive message generation and delivery pipeline."""

from __future__ import annotations

import difflib
import math
import random
import re
import time as time_module
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from src.wa_agent.whatsapp import send_whatsapp_text


ACCESS_TOKEN = ""
PHONE_NUMBER_ID = ""


def hk_now() -> datetime:
    return datetime.now(timezone.utc).astimezone()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso_dt(text: str) -> Optional[datetime]:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def _normalize_key(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]", "", text.lower())
    return cleaned[:100]


def _normalize_bucket(bucket: str) -> str:
    if not bucket:
        return "within_7d"
    bucket = bucket.lower().strip()
    if bucket in ("within_24h", "within_day", "day"):
        return "within_24h"
    if bucket in ("within_30d", "within_month", "month"):
        return "within_30d"
    return "within_7d"


RECENT_MEMORY_BUCKET_HOURS = {
    "within_24h": 24,
    "within_3d": 72,
    "within_7d": 24 * 7,
}
LEGACY_RECENT_BUCKETS = {
    "today": "within_24h",
    "tonight": "within_24h",
    "last_night": "within_3d",
    "recent_days": "within_7d",
}
RECENT_MEMORY_BUCKET_LABELS = {
    "within_24h": "24小時內",
    "within_3d": "三天內",
    "within_7d": "一週內",
}


def normalize_recent_bucket(bucket: str) -> str:
    value = _clean_text(bucket)
    if value in LEGACY_RECENT_BUCKETS:
        value = LEGACY_RECENT_BUCKETS[value]
    if value in RECENT_MEMORY_BUCKET_HOURS:
        return value
    return "within_7d"


def recent_bucket_label(bucket: str) -> str:
    return RECENT_MEMORY_BUCKET_LABELS.get(normalize_recent_bucket(bucket), "一週內")


def current_recent_bucket(observed_at: str, now: Optional[datetime] = None) -> str:
    observed = _parse_iso_dt(observed_at)
    if not observed:
        return "within_7d"
    now_utc = (now or hk_now()).astimezone(timezone.utc)
    age = now_utc - observed.astimezone(timezone.utc)
    if age <= timedelta(hours=24):
        return "within_24h"
    if age <= timedelta(hours=72):
        return "within_3d"
    if age <= timedelta(hours=168):
        return "within_7d"
    return ""


def format_memory_timestamp(value: str) -> str:
    parsed = _parse_iso_dt(value)
    if not parsed:
        return ""
    return parsed.astimezone(hk_now().tzinfo).strftime("%m-%d %H:%M")


SHORT_TERM_MEMORY_RETENTION_HOURS = 168


def _short_term_expiry(observed_text: str) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=SHORT_TERM_MEMORY_RETENTION_HOURS)


def _service_day_start(now: Optional[datetime] = None) -> datetime:
    now = now or hk_now()
    boundary = now.replace(hour=5, minute=0, second=0, microsecond=0)
    if now.hour < 5:
        boundary = boundary - timedelta(days=1)
    return boundary


def _service_day_end(now: Optional[datetime] = None) -> datetime:
    now = now or hk_now()
    boundary = now.replace(hour=4, minute=59, second=59, microsecond=0)
    if now.hour >= 5:
        boundary = boundary + timedelta(days=1)
    return boundary


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _is_night_mode(now: Optional[datetime] = None) -> bool:
    if now is None:
        now = hk_now()
    return now.hour >= 22 or now.hour < 1


def _get_time_profile(now: Optional[datetime] = None) -> str:
    if now is None:
        now = hk_now()
    hour = now.hour
    if 7 <= hour < 9:
        return "morning"
    elif 9 <= hour < 17:
        return "busy_day"
    elif 17 <= hour < 22:
        return "evening"
    else:
        return "late_night"


def style_window_text(now: Optional[datetime] = None) -> str:
    profile = _get_time_profile(now)
    if profile == "morning":
        return "早上時段（7-9點）：語氣輕快、自然關心，偏向早餐、上堂、醒咗未呢類話題。"
    if profile == "busy_day":
        return "忙碌時段（9-17點）：語氣簡短、偏向輕輕問候，唔好太長或太黏。"
    if profile == "evening":
        return "晚間時段（17-22點）：語氣輕鬆，可以多啲關心、撒嬌成分。"
    return "深夜時段（22-7點）：語氣温柔、低打擾，偏向關心同少少掛住佢。"


def proactive_slot_key(now: Optional[datetime] = None) -> str:
    if now is None:
        now = hk_now()
    hour = now.hour
    if 7 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 22:
        return "evening"
    return "late_night"


def proactive_slot_hint(now: Optional[datetime] = None) -> str:
    slot = proactive_slot_key(now)
    if slot == "morning":
        return "朝早主動搵佢時，偏向輕輕關心、早餐、上堂、瞓醒未呢類自然開場。"
    if slot == "afternoon":
        return "下晝主動搵佢時，偏向問佢上堂、食晏、忙唔忙，語氣自然啲、輕輕一句就夠，唔好太黏。"
    if slot == "evening":
        return "夜晚主動搵佢時，偏向關心加少少撒嬌，可以接住佢今日做過嘅事、食咗咩、去咗邊。"
    return "夜深主動搵佢時要溫柔啲、低打擾啲，但可以再黏少少，似真係掛住佢先輕輕搵一句。"


def _generate_model_text(prompt: str, temperature: float = 0.72, max_tokens: int = 90) -> str:
    """Generate text using brain bridge. Import at call time."""
    from brain_adapter import call_brain_bridge
    return call_brain_bridge(prompt, temperature=temperature, max_tokens=max_tokens)


def split_profile_memory_lines(value: str) -> list[str]:
    lines = []
    for raw_line in str(value or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = re.sub(r"^\s*[-*•]+\s*", "", raw_line).strip()
        line = _clean_text(line)
        if line:
            lines.append(line)
    return lines


def memories_look_duplicated(left: str, right: str) -> bool:
    left_key = _normalize_key(left)
    right_key = _normalize_key(right)
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


def build_core_profile_memory_text(primary_text: str, max_lines: int = 10, max_chars: int = 1800) -> str:
    kept = []
    current_chars = 0
    for line in split_profile_memory_lines(primary_text):
        if any(memories_look_duplicated(line, existing) for existing in kept):
            continue
        next_chars = current_chars + len(line) + 2
        if kept and next_chars > max_chars:
            break
        kept.append(line)
        current_chars = next_chars
        if len(kept) >= max_lines:
            break
    if not kept:
        return primary_text or "（暫時未有核心檔案）"
    return "\n".join(f"- {line}" for line in kept)


def build_filtered_long_term_memory_lines(rows: list[dict], primary_text: str, limit: int = 20) -> list[str]:
    primary_lines = split_profile_memory_lines(primary_text)
    kept = []
    seen_texts = []
    for row in rows:
        content = _clean_text(row.get("content", ""))
        if not content:
            continue
        if any(memories_look_duplicated(content, primary_line) for primary_line in primary_lines):
            continue
        if any(memories_look_duplicated(content, existing) for existing in seen_texts):
            continue
        kept.append(f"- {content}")
        seen_texts.append(content)
        if len(kept) >= limit:
            break
    return kept


def _get_runtime_settings() -> dict:
    """Get runtime settings from database."""
    from src.wa_agent.db import MemoryDB
    db = MemoryDB()
    conn = db.get_connection()
    rows = conn.execute("SELECT key, value FROM susu_runtime_settings").fetchall()
    settings = {row["key"]: row["value"] for row in rows}
    defaults = {
        "proactive_enabled": "true",
        "proactive_conversation_window_hours": "14",
        "proactive_min_silence_minutes": "25",
        "proactive_cooldown_minutes": "30",
        "proactive_min_inbound_messages": "3",
        "proactive_max_per_service_day": "3",
        "proactive_reply_window_minutes": "35",
        "proactive_scan_seconds": "300",
        "primary_user_memory": "",
    }
    for k, v in defaults.items():
        if k not in settings:
            settings[k] = v
    db.close()
    return settings


ADMIN_WA_ID = ""


def primary_profile_memory_for_wa(wa_id: str, settings: Optional[dict] = None) -> str:
    settings = settings or _get_runtime_settings()
    if (wa_id or "").strip() != ADMIN_WA_ID:
        return ""
    return settings.get("primary_user_memory", "")


def load_image_stats_summary(conn, wa_id: str) -> str:
    rows = conn.execute(
        "SELECT category, count FROM wa_image_stats WHERE wa_id = ? ORDER BY count DESC, category ASC LIMIT 4",
        (wa_id,),
    ).fetchall()
    if not rows:
        return ""
    return "、".join(f"{row['category']}({row['count']})" for row in rows if row["count"] > 0)


def format_quote_context_suffix(item: dict) -> str:
    quoted_message_id = _clean_text(item.get("quoted_message_id", ""))
    if not quoted_message_id:
        return ""
    quoted_preview = _clean_text(item.get("quoted_preview", ""))
    if quoted_preview and quoted_preview != "較早訊息":
        return f"（回覆 {quoted_preview}）"
    return "（回覆較早訊息）"


def normalize_session_content(content: str) -> str:
    return _clean_text(content)


def load_session_memory_rows(conn, wa_id: str, limit: int = 6, bucket: Optional[str] = None) -> list[dict]:
    if bucket:
        rows = conn.execute(
            "SELECT content, memory_key, bucket, observed_at, updated_at FROM wa_session_memories WHERE wa_id=? AND bucket=? ORDER BY observed_at DESC LIMIT ?",
            (wa_id, bucket, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT content, memory_key, bucket, observed_at, updated_at FROM wa_session_memories WHERE wa_id=? ORDER BY observed_at DESC LIMIT ?",
            (wa_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def format_session_memory_lines(conn, wa_id: str, bucket: str, limit: int = 6) -> list[str]:
    rows = load_session_memory_rows(conn, wa_id, limit=limit, bucket=bucket)
    if not rows:
        return []
    formatted = []
    seen = set()
    for row in rows:
        content = normalize_session_content(row.get("content", ""))
        if not content:
            continue
        key = _normalize_key(content)
        if key in seen:
            continue
        seen.add(key)
        bucket_value = row.get("current_bucket") or current_recent_bucket(row.get("observed_at") or row.get("updated_at")) or normalize_recent_bucket(row.get("bucket", bucket))
        stamp = format_memory_timestamp(row.get("observed_at") or row.get("updated_at", ""))
        tag = recent_bucket_label(bucket_value)
        if stamp:
            formatted.append(f"- [{tag} | {stamp}] {content}")
        else:
            formatted.append(f"- [{tag}] {content}")
    return formatted


def load_recent_messages(conn, wa_id: str, limit: int = 8) -> list[dict]:
    rows = conn.execute(
        "SELECT id, direction, message_id, message_type, body, quoted_message_id, quoted_preview, created_at FROM wa_messages WHERE wa_id=? ORDER BY id DESC LIMIT ?",
        (wa_id, limit),
    ).fetchall()
    return [dict(row) for row in reversed(rows)]


def load_memories(conn, wa_id: str, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        "SELECT kind, content, importance, updated_at, created_at FROM wa_memories WHERE wa_id=? ORDER BY importance DESC, updated_at DESC, id DESC LIMIT ?",
        (wa_id, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def get_last_message_time(conn, wa_id: str, direction: Optional[str] = None) -> Optional[datetime]:
    if direction:
        row = conn.execute(
            "SELECT created_at FROM wa_messages WHERE wa_id=? AND direction=? ORDER BY id DESC LIMIT 1",
            (wa_id, direction),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT created_at FROM wa_messages WHERE wa_id=? ORDER BY id DESC LIMIT 1",
            (wa_id,),
        ).fetchone()
    if not row:
        return None
    return _parse_iso_dt(row["created_at"])


def get_last_message_row(conn, wa_id: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT id, direction, message_id, message_type, body, created_at FROM wa_messages WHERE wa_id=? ORDER BY id DESC LIMIT 1",
        (wa_id,),
    ).fetchone()
    return dict(row) if row else None


def get_pending_proactive_event(conn, wa_id: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM wa_proactive_events WHERE wa_id=? AND outcome='pending' ORDER BY id DESC LIMIT 1",
        (wa_id,),
    ).fetchone()
    return dict(row) if row else None


def get_last_proactive_event(conn, wa_id: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM wa_proactive_events WHERE wa_id=? ORDER BY id DESC LIMIT 1",
        (wa_id,),
    ).fetchone()
    return dict(row) if row else None


def count_inbound_messages(conn, wa_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) as c FROM wa_messages WHERE wa_id=? AND direction='inbound'",
        (wa_id,),
    ).fetchone()
    return row["c"] if row else 0


def count_proactive_for_service_day(conn, wa_id: str, now: Optional[datetime] = None) -> int:
    now = now or hk_now()
    start_text = _service_day_start(now).astimezone(timezone.utc).isoformat()
    row = conn.execute(
        "SELECT COUNT(*) AS total FROM wa_proactive_events WHERE wa_id=? AND created_at >= ? AND outcome IN ('pending', 'replied', 'ignored')",
        (wa_id, start_text),
    ).fetchone()
    return int(row["total"]) if row else 0


def get_slot_success_rate(conn, wa_id: str, slot_key: str) -> float:
    row = conn.execute(
        "SELECT success_count, fail_count FROM wa_proactive_slot_stats WHERE wa_id=? AND slot_key=?",
        (wa_id, slot_key),
    ).fetchone()
    if not row or (row["success_count"] + row["fail_count"]) == 0:
        return 0.5
    return row["success_count"] / (row["success_count"] + row["fail_count"])


def _bump_proactive_slot_outcome(conn, wa_id: str, slot_key: str, success: bool) -> None:
    now_text = utc_now()
    conn.execute(
        """
        INSERT INTO wa_proactive_slot_stats (wa_id, slot_key, success_count, fail_count, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(wa_id, slot_key) DO UPDATE SET
            success_count=success_count + excluded.success_count,
            fail_count=fail_count + excluded.fail_count,
            updated_at=excluded.updated_at
        """,
        (
            wa_id,
            slot_key,
            1 if success else 0,
            0 if success else 1,
            now_text,
        ),
    )


def finalize_stale_proactive_events(conn, wa_id: Optional[str] = None) -> None:
    settings = _get_runtime_settings()
    reply_window_minutes = int(settings.get("proactive_reply_window_minutes", "35"))
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=reply_window_minutes)).isoformat()
    sql = "SELECT id, wa_id, slot_key FROM wa_proactive_events WHERE outcome = 'pending' AND created_at < ?"
    params: list = [cutoff]
    if wa_id:
        sql += " AND wa_id = ?"
        params.append(wa_id)
    rows = conn.execute(sql, params).fetchall()
    for row in rows:
        conn.execute(
            "UPDATE wa_proactive_events SET outcome = 'ignored', reward = 0 WHERE id = ?",
            (row["id"],),
        )
        _bump_proactive_slot_outcome(conn, row["wa_id"], row["slot_key"], False)


from src.wa_agent.brain import shorten_whatsapp_reply, split_reply_bubbles, maybe_stage_followup_bubbles


def build_proactive_prompt(conn, wa_id: str, profile_name: str, now: Optional[datetime] = None) -> str:
    now = now or hk_now()
    settings = _get_runtime_settings()
    primary_text = primary_profile_memory_for_wa(wa_id, settings)
    history_lines = []
    for item in load_recent_messages(conn, wa_id, limit=8):
        speaker = "對方" if item.get("direction") == "inbound" else "蘇蘇"
        body = _clean_text(item.get("body", ""))
        if body:
            history_lines.append(f"{speaker}{format_quote_context_suffix(item)}: {body}")

    dynamic_memories = build_filtered_long_term_memory_lines(load_memories(conn, wa_id), primary_text, limit=20)
    within_24h_memories = format_session_memory_lines(conn, wa_id, "within_24h", limit=4)
    within_3d_memories = format_session_memory_lines(conn, wa_id, "within_3d", limit=4)
    within_7d_memories = format_session_memory_lines(conn, wa_id, "within_7d", limit=4)
    image_stats_text = load_image_stats_summary(conn, wa_id)

    history_text = "\n".join(history_lines[-8:]) if history_lines else "（最近未有聊天）"
    core_profile_text = build_core_profile_memory_text(primary_text) if primary_text else "（主號核心檔案暫未設定）"
    memory_text = "\n".join(dynamic_memories) if dynamic_memories else "（暫時未有補充長期記憶）"
    within_24h_text = "\n".join(within_24h_memories) if within_24h_memories else "（暫時未有 24 小時內記憶）"
    within_3d_text = "\n".join(within_3d_memories) if within_3d_memories else "（暫時未有三天內記憶）"
    within_7d_text = "\n".join(within_7d_memories) if within_7d_memories else "（暫時未有一週內記憶）"

    image_hint = ""
    if image_stats_text:
        image_hint = f"\n對方平時 send 圖偏多嘅類型：{image_stats_text}"

    return f"""
對方 WhatsApp 顯示名稱：{profile_name or "對方"}

主號核心檔案：
{core_profile_text}

補充長期記憶（已避開與核心檔案重複項）：
{memory_text}

24 小時內記憶：
{within_24h_text}

三天內記憶：
{within_3d_text}

一週內記憶：
{within_7d_text}

最近聊天：
{history_text}{image_hint}

時段風格：
{style_window_text(now)}

主動開場提示：
{proactive_slot_hint(now)}

你而家想主動搵對方開話題。請直接輸出一段自然、似真人 WhatsApp 嘅主動訊息：
- 要似女朋友突然掛住佢、順手搵佢，唔好似客服 check in
- 優先接住最近聊天、短期狀態或者你記得嘅生活細節
- 如果冇明顯 hook，就簡單關心或者輕輕撒嬌
- 如果係下晝，偏向輕輕問一句就夠，唔好太黏
- 如果係夜晚或者夜深，偏向關心加少少撒嬌，似真係掛住佢
- 日頭偏向 1 句，夜晚最多 2 句
- 唔好太刻意，唔好解釋點解主動搵佢
- 唔好催瞓，除非對方主動提起想瞓
- 直接輸出要發嘅內容本身
""".strip()


def evaluate_proactive_candidate(conn, wa_id: str, profile_name: str = "", now: Optional[datetime] = None) -> dict:
    now = now or hk_now()
    now_utc = now.astimezone(timezone.utc)
    settings = _get_runtime_settings()
    conversation_window_hours = int(settings.get("proactive_conversation_window_hours", "14"))
    min_silence_minutes = int(settings.get("proactive_min_silence_minutes", "25"))
    cooldown_minutes = int(settings.get("proactive_cooldown_minutes", "30"))
    min_inbound_messages = int(settings.get("proactive_min_inbound_messages", "3"))
    max_per_service_day = int(settings.get("proactive_max_per_service_day", "3"))
    finalize_stale_proactive_events(conn, wa_id)

    last_inbound = get_last_message_time(conn, wa_id, "inbound")
    if not last_inbound:
        return {"eligible": False, "reason": "no_inbound"}
    if now_utc - last_inbound > timedelta(hours=conversation_window_hours):
        return {"eligible": False, "reason": "window_closed"}

    last_row = get_last_message_row(conn, wa_id)
    if not last_row:
        return {"eligible": False, "reason": "no_messages"}
    if last_row.get("direction") != "outbound":
        return {"eligible": False, "reason": "awaiting_reply"}

    last_any = _parse_iso_dt(last_row.get("created_at", ""))
    if not last_any:
        return {"eligible": False, "reason": "no_last_message_time"}

    silence_minutes = max((now_utc - last_any).total_seconds() / 60.0, 0.0)
    if silence_minutes < min_silence_minutes:
        return {"eligible": False, "reason": "cooling", "silence_minutes": silence_minutes}

    if get_pending_proactive_event(conn, wa_id):
        return {"eligible": False, "reason": "pending_proactive"}

    last_proactive = get_last_proactive_event(conn, wa_id)
    if last_proactive:
        last_proactive_at = _parse_iso_dt(last_proactive.get("created_at", ""))
        if last_proactive_at and now_utc - last_proactive_at < timedelta(minutes=cooldown_minutes):
            return {"eligible": False, "reason": "proactive_cooldown"}

    if count_inbound_messages(conn, wa_id) < min_inbound_messages:
        return {"eligible": False, "reason": "too_new"}

    daily_count = count_proactive_for_service_day(conn, wa_id, now)
    if daily_count >= max_per_service_day:
        return {"eligible": False, "reason": "daily_cap"}

    slot_key = proactive_slot_key(now)
    slot_rate = get_slot_success_rate(conn, wa_id, slot_key)
    recent_hook_count = sum(
        len(format_session_memory_lines(conn, wa_id, bucket, limit=3))
        for bucket in ("within_24h", "within_3d", "within_7d")
    )
    image_bonus = 0.08 if load_image_stats_summary(conn, wa_id) else 0.0
    silence_bonus = min(max((silence_minutes - min_silence_minutes) / 180.0, 0.0), 1.0) * 1.2
    slot_bias = {"morning": -0.22, "afternoon": 0.18, "evening": 0.88, "late_night": 0.76}.get(slot_key, 0.0)
    relationship_bonus = min(recent_hook_count, 3) * 0.12
    history_bonus = (slot_rate - 0.5) * 1.6
    age_penalty = -0.35 if (now_utc - last_inbound) > timedelta(hours=8) else 0.0
    late_penalty = -0.25 if 1 <= now.hour < 8 else 0.0
    score = -1.95 + silence_bonus + slot_bias + relationship_bonus + history_bonus + image_bonus + age_penalty + late_penalty - (daily_count * 0.55)
    probability = min(0.70, max(0.08, _sigmoid(score)))
    return {
        "eligible": True,
        "wa_id": wa_id,
        "profile_name": profile_name,
        "slot_key": slot_key,
        "score": round(score, 4),
        "probability": round(probability, 4),
        "silence_minutes": round(silence_minutes, 1),
        "daily_count": daily_count,
        "slot_rate": round(slot_rate, 4),
    }


PROACTIVE_SCAN_SECONDS = 300


def send_proactive_message(conn, candidate: dict, now: Optional[datetime] = None) -> dict:
    now = now or hk_now()
    wa_id = candidate["wa_id"]
    profile_name = candidate.get("profile_name", "")
    prompt = build_proactive_prompt(conn, wa_id, profile_name, now)
    reply = shorten_whatsapp_reply(
        _generate_model_text(
            prompt,
            temperature=0.8 if _is_night_mode(now) else 0.72,
            max_tokens=120 if _is_night_mode(now) else 90,
        ),
        night_mode=_is_night_mode(now),
    )
    if not reply:
        return {"ok": False, "reason": "empty_reply"}

    bubbles = split_reply_bubbles(reply, night_mode=_is_night_mode(now))
    bubbles = maybe_stage_followup_bubbles(bubbles, night_mode=_is_night_mode(now))
    body_text = "\n".join(bubbles)
    created_at = utc_now()
    cursor = conn.execute(
        """
        INSERT INTO wa_proactive_events (wa_id, slot_key, trigger_type, probability, score, body, prompt, created_at, outcome)
        VALUES (?, ?, 'idle_check', ?, ?, ?, ?, ?, 'pending')
        """,
        (
            wa_id,
            candidate["slot_key"],
            candidate["probability"],
            candidate["score"],
            body_text,
            prompt,
            created_at,
        ),
    )
    event_id = cursor.lastrowid

    try:
        for index, bubble in enumerate(bubbles):
            response = send_whatsapp_text(wa_id, bubble)
            conn.execute(
                """
                INSERT INTO wa_messages (wa_id, direction, message_id, message_type, body, raw_json, created_at)
                VALUES (?, 'outbound', ?, 'text', ?, ?, ?)
                """,
                (
                    wa_id,
                    (response.get("messages") or [{}])[0].get("id", ""),
                    bubble,
                    json.dumps(response, ensure_ascii=False),
                    utc_now(),
                ),
            )
            conn.commit()
            if index < len(bubbles) - 1:
                time_module.sleep(1.0)
    except Exception as exc:
        conn.execute(
            "UPDATE wa_proactive_events SET outcome = 'send_failed', reward = 0 WHERE id = ?",
            (event_id,),
        )
        conn.execute(
            "INSERT INTO wa_messages (wa_id, direction, message_id, message_type, body, raw_json, created_at) VALUES (?, 'outbound', '', 'error', ?, ?, ?)",
            (
                wa_id,
                f"proactive_send_failed: {exc}",
                json.dumps({"error": str(exc)}, ensure_ascii=False),
                utc_now(),
            ),
        )
        conn.commit()
        return {"ok": False, "reason": f"send_failed: {exc}"}

    return {"ok": True, "event_id": event_id, "body": body_text}


import json


def run_proactive_scan_once() -> dict:
    settings = _get_runtime_settings()
    if not settings.get("proactive_enabled", "true").lower() in ("true", "1", "yes"):
        return {"ok": True, "status": "disabled"}
    global ACCESS_TOKEN, PHONE_NUMBER_ID
    ACCESS_TOKEN = settings.get("WA_ACCESS_TOKEN", "") or ""
    PHONE_NUMBER_ID = settings.get("WA_PHONE_NUMBER_ID", "") or ""
    if not ACCESS_TOKEN or not PHONE_NUMBER_ID:
        return {"ok": False, "status": "missing_whatsapp_credentials"}

    from src.wa_agent.db import MemoryDB
    db = MemoryDB()
    conn = db.get_connection()
    try:
        finalize_stale_proactive_events(conn)
        contacts = conn.execute(
            "SELECT wa_id, profile_name FROM wa_contacts ORDER BY updated_at DESC LIMIT 12"
        ).fetchall()
        triggered = []
        checked = 0
        now = hk_now()
        for row in contacts:
            checked += 1
            candidate = evaluate_proactive_candidate(conn, row["wa_id"], row["profile_name"], now)
            if not candidate.get("eligible"):
                continue
            if random.random() >= candidate["probability"]:
                continue
            result = send_proactive_message(conn, candidate, now)
            if result.get("ok"):
                triggered.append({"wa_id": row["wa_id"], "probability": candidate["probability"]})
        conn.commit()
        return {"ok": True, "status": "scanned", "checked": checked, "triggered": triggered}
    finally:
        db.close()


def proactive_loop() -> None:
    """Infinite loop that periodically scans for proactive message candidates."""
    while True:
        try:
            run_proactive_scan_once()
        except Exception:
            pass
        scan_seconds = int(_get_runtime_settings().get("proactive_scan_seconds", str(PROACTIVE_SCAN_SECONDS)))
        time_module.sleep(max(scan_seconds, 60))
