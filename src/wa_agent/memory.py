"""Memory extraction and storage — long-term and session memories."""

from __future__ import annotations

import re
from typing import Optional

from src.ai.config import AIConfig


MEMORY_EXTRACTOR_PROMPT = """你係一個精確嘅記憶管理助手。每次你會睇到對方嘅現有記憶，以及佢哋最新嘅說話。你要判斷有冇新嘅穩定長期資訊係值得記錄低嘅。

注意：
- 只抽取真正長期、穩定、有持續價值嘅資訊
- 唔好抽取一次性、短期或時效性嘅資訊
- 唔好重複已經喺現有記憶入面嘅資訊
- 輸出 JSON 格式，每項包含 content 同 importance（1-5）
"""


RECENT_MEMORY_EXTRACTOR_PROMPT = """你係一個短期記憶助手。請從對方最新說話中抽取值得保留嘅短期記憶（24小時至7天內有用）。

分類：
- within_24h：24小時內（例如：今日、今晚、頭先、啱啱）
- within_3d：三天內（例如：尋晚、昨日、聽日、後天）
- within_7d：一星期內（例如：呢兩三日、今個星期、近期）

注意：
- 唔好抽取長期背景或偏好
- 一次性情緒、純撒嬌、問候句唔需要記
- 輸出 JSON 格式，每項包含 content 同 bucket
"""


def is_long_term_memory_candidate(text: str) -> bool:
    """Check if text is a good candidate for long-term memory."""
    if not text or len(text.strip()) < 6:
        return False
    short_phrases = ["你好", "hi", "hello", "早晨", "晚安", "thank you", "謝謝"]
    if text.lower().strip() in short_phrases:
        return False
    if len(text) > 200:
        return False
    return True


def is_recent_memory_candidate(text: str) -> bool:
    """Check if text is a good candidate for session memory."""
    if not text or len(text.strip()) < 4:
        return False
    if len(text) > 300:
        return False
    return True


def normalize_key(text: str) -> str:
    """Create a normalized key for memory deduplication."""
    cleaned = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]", "", text.lower())
    return cleaned[:100]


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


def clean_text(value: str) -> str:
    """Remove zero-width characters and normalize whitespace."""
    text = str(value or "").replace("\u200b", "").replace("\u200c", "").replace("\u200d", "").replace("\ufeff", "")
    return re.sub(r"\s+", " ", text.strip())


def normalize_recent_bucket(bucket: str) -> str:
    """Normalize a bucket name to one of the valid values."""
    value = clean_text(bucket)
    if value in LEGACY_RECENT_BUCKETS:
        value = LEGACY_RECENT_BUCKETS[value]
    if value in RECENT_MEMORY_BUCKET_HOURS:
        return value
    return "within_7d"


def classify_recent_memory_bucket(text: str) -> str:
    """Classify a piece of text into a time bucket based on keywords."""
    text_lower = text.lower()
    if any(kw in text_lower for kw in ["今日", "今天", "今晚", "頭先", "啱啱", "而家", "現在"]):
        return "within_24h"
    if any(kw in text_lower for kw in ["尋晚", "昨日", "聽日", "明天", "後天", "聽日"]):
        return "within_3d"
    return "within_7d"


class MemoryManager:
    """
    Memory extraction and storage manager.
    
    Handles:
    - Long-term memory extraction and storage
    - Session memory extraction and storage  
    - Memory deduplication and importance scoring
    - Heuristic memory extraction as fallback
    """

    def __init__(self, config: AIConfig, memory_db=None):
        self.config = config
        self.memory_db = memory_db

    def extract_and_save_long_term(
        self,
        conn,
        wa_id: str,
        profile_name: str,
        incoming_text: str,
    ) -> list[dict]:
        """
        Extract long-term memories from incoming text and save them.
        
        Returns:
            List of saved memory dicts with content and importance.
        """
        raise NotImplementedError("Full implementation pending Phase 7 integration")

    def extract_and_save_session(
        self,
        conn,
        wa_id: str,
        incoming_text: str,
    ) -> list[str]:
        """
        Extract session memories from incoming text and save them.
        
        Returns:
            List of saved memory content strings.
        """
        raise NotImplementedError("Full implementation pending Phase 7 integration")

    def is_long_term_candidate(self, text: str) -> bool:
        return is_long_term_memory_candidate(text)

    def is_recent_candidate(self, text: str) -> bool:
        return is_recent_memory_candidate(text)

    def normalize_key(self, text: str) -> str:
        return normalize_key(text)

    def normalize_bucket(self, bucket: str) -> str:
        return normalize_recent_bucket(bucket)

    def classify_bucket(self, text: str) -> str:
        return classify_recent_memory_bucket(text)
