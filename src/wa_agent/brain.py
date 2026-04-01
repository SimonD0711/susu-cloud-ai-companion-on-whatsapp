"""Reply generation brain — generates LLM responses for WhatsApp messages."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from src.ai.config import AIConfig
from src.ai.llm.manager import LLMManager


MAX_INLINE_REPLY_EMOJIS = 1
PUNCTUATION = "。！？!?~～…"


def is_emoji_base_char(char: str) -> bool:
    if not char:
        return False
    codepoint = ord(char)
    return (
        0x1F300 <= codepoint <= 0x1FAFF
        or 0x2600 <= codepoint <= 0x26FF
        or 0x2700 <= codepoint <= 0x27BF
    )


def is_emoji_modifier_char(char: str) -> bool:
    if not char:
        return False
    codepoint = ord(char)
    return codepoint in (0xFE0F, 0x200D) or 0x1F3FB <= codepoint <= 0x1F3FF


def trim_inline_reply_emojis(text: str, max_emojis: int = 1) -> str:
    if not text:
        return ""
    keep_limit = max(int(max_emojis), 0)
    kept = 0
    keeping_cluster = False
    out = []
    for char in text:
        if is_emoji_base_char(char):
            if kept >= keep_limit:
                keeping_cluster = False
                continue
            kept += 1
            keeping_cluster = True
            out.append(char)
            continue
        if is_emoji_modifier_char(char):
            if keeping_cluster:
                out.append(char)
            continue
        keeping_cluster = False
        out.append(char)
    collapsed = "".join(out)
    collapsed = re.sub(r" {2,}", " ", collapsed)
    collapsed = re.sub(r" *\n *", "\n", collapsed)
    return collapsed.strip()


def normalize_reply(reply: str) -> str:
    text = (reply or "").strip().replace("\r", "\n")
    text = text.replace("——", " ").replace("--", " ").replace("—", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = trim_inline_reply_emojis(text, max_emojis=MAX_INLINE_REPLY_EMOJIS)
    return text.strip(" \"'`")[:2000].strip()


def shorten_whatsapp_reply(reply: str, night_mode: bool = False) -> str:
    """Shorten and clean a WhatsApp reply."""
    return normalize_reply(reply)


def looks_fragmentary(reply: str, incoming_text: str) -> bool:
    """Check if reply appears to be cut off mid-sentence."""
    text = normalize_reply(reply)
    if not text:
        return True
    stripped = re.sub(r"[。！？!?~～…\s]", "", text)
    if len(stripped) < 4:
        return True
    if text.startswith(("因為", "所以", "如果", "但係", "同埋", "然後", "或者")) and len(stripped) < 12:
        return True
    if "\n" not in text and not any(text.endswith(mark) for mark in PUNCTUATION) and len(stripped) < 14:
        if not any(text.endswith(p) for p in ("喇", "囉", "啫", "呀", "wo", "la", "le", "ah", "嘛", "既", "ge")):
            return True
    if len(text.split()) <= 2 and len(stripped) < 8:
        return True
    if incoming_text.strip() and len(incoming_text.strip()) > 3 and len(stripped) < 6:
        return True
    return False


def contains_sleep_nag(text: str) -> bool:
    """Check if text contains sleep nudging."""
    if not text:
        return False
    return any(kw in text for kw in ["早啲訓", "早點睡", "去訓啦", "去睡啦", "快啲訓", "快點睡", "夜晚唔好", "訓覺啦"])


def is_night_mode(now: datetime) -> bool:
    """Check if current time is in night mode (22-00h)."""
    return now.hour >= 22 or now.hour < 1


def get_time_profile(now: datetime) -> str:
    """Get the time profile for the current time."""
    hour = now.hour
    if 7 <= hour < 9:
        return "morning"
    elif 9 <= hour < 17:
        return "busy_day"
    elif 17 <= hour < 22:
        return "evening"
    else:
        return "late_night"


class ReplyBrain:
    """
    Central reply generation brain.
    
    Wraps the full reply generation pipeline including:
    - Live search integration
    - Temperature/max_tokens profile selection
    - Sleep boundary handling
    - Brain bridge fallback
    - Reply shortening and repair
    """

    def __init__(self, config: AIConfig, llm_manager: Optional[LLMManager] = None):
        self.config = config
        self.llm = llm_manager or LLMManager(config)

    def generate(
        self,
        conn,
        wa_id: str,
        profile_name: str,
        incoming_text: str,
        image_inputs: list | None = None,
        image_categories: list | None = None,
        toggle_result: str = "unchanged",
    ) -> str:
        """
        Generate a WhatsApp reply.
        
        Args:
            conn: SQLite connection
            wa_id: WhatsApp ID
            profile_name: Contact display name
            incoming_text: Incoming message text
            image_inputs: Optional list of image input dicts
            image_categories: Optional list of image category strings
            toggle_result: Voice mode toggle result ("enabled", "disabled", "unchanged")
        
        Returns:
            The generated reply text.
        """
        raise NotImplementedError("Full generate() implementation pending Phase 7 integration")

    def _shorten(self, text: str, night_mode: bool = False) -> str:
        return shorten_whatsapp_reply(text, night_mode=night_mode)

    def _looks_fragmentary(self, reply: str, incoming: str) -> bool:
        return looks_fragmentary(reply, incoming)

    def _contains_sleep_nag(self, text: str) -> bool:
        return contains_sleep_nag(text)

    def _is_night_mode(self, now: datetime) -> bool:
        return is_night_mode(now)

    def _get_time_profile(self, now: datetime) -> str:
        return get_time_profile(now)
