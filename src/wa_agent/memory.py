"""Memory extraction and storage — long-term and session memories."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
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

⚠️ 時間詞指嘅係「事件發生嘅時間」，唔係「對方講呢句說話嘅時間」！
- 「昨天吃了包子」→ 事件發生喺昨天 → bucket = within_3d
- 「今日約咗朋友」→ 事件發生喺今日 → bucket = within_24h
- 「聽日考試」→ 事件發生喺明天 → bucket = within_3d

分類：
- within_24h：頭先、啱啱、今日（事件發生在今日）、今晚、今朝
- within_3d：尋晚、昨日、聽日、明天、後天、呢兩三日
- within_7d：最近、近排、今個星期、最近幾日、最近嘅短期計劃或任務

唔好抽取：
- 長期背景、長期偏好、長期習慣
- 冇資訊量嘅撒嬌、純情緒、客套句
- 太私密或太敏感嘅細節

輸出 JSON 格式，每項包含 content 同 bucket。
"""


RECENT_24H_MARKERS = (
    "而家", "宜家", "我而家", "依家", "頭先", "啱啱", "剛剛", "刚刚", "今日", "今天",
    "今晚", "今晩", "今朝", "今早", "朝早", "下晝", "下午", "凌晨", "今個下晝",
)
RECENT_3D_MARKERS = (
    "尋晚", "昨晚", "琴晚", "噚晚", "昨日", "琴日", "噚日", "前日", "聽日", "听日",
    "明天", "明日", "聽朝", "听朝", "明早", "後日", "后天", "大後日", "大后天", "呢兩日",
    "这两日", "這兩日", "這兩三日", "呢三日",
)
RECENT_7D_MARKERS = (
    "最近", "近排", "呢排", "近期", "這幾日", "呢幾日", "今個星期", "今個禮拜", "呢星期",
    "本週", "本周", "這星期", "今周", "這一週",
)


def is_long_term_memory_candidate(text: str) -> bool:
    if not text or len(text.strip()) < 6:
        return False
    short_phrases = ["你好", "hi", "hello", "早晨", "晚安", "thank you", "謝謝"]
    if text.lower().strip() in short_phrases:
        return False
    if len(text) > 200:
        return False
    return True


def is_recent_memory_candidate(text: str) -> bool:
    if not text or len(text.strip()) < 4:
        return False
    if len(text) > 300:
        return False
    return True


def normalize_key(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]", "", text.lower())
    return cleaned[:160]


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
    text = str(value or "").replace("\u200b", "").replace("\u200c", "").replace("\u200d", "").replace("\ufeff", "")
    return re.sub(r"\s+", " ", text.strip())


def normalize_recent_bucket(bucket: str) -> str:
    value = clean_text(bucket)
    if value in LEGACY_RECENT_BUCKETS:
        value = LEGACY_RECENT_BUCKETS[value]
    if value in RECENT_MEMORY_BUCKET_HOURS:
        return value
    return "within_7d"


def classify_recent_memory_bucket(text: str) -> str:
    value = clean_text(text)
    if any(marker in value for marker in RECENT_24H_MARKERS):
        return "within_24h"
    if any(marker in value for marker in RECENT_3D_MARKERS):
        return "within_3d"
    if any(marker in value for marker in RECENT_7D_MARKERS):
        return "within_7d"
    return "within_7d"


def infer_observed_at_from_text(text: str, now: Optional[datetime] = None) -> Optional[datetime]:
    value = clean_text(text)
    if not value:
        return None
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    shift_days = 0

    PAST_MARKERS = {
        "頭先": 0, "啱啱": 0, "剛剛": 0, "刚刚": 0, "而家": 0, "宜家": 0, "我而家": 0, "依家": 0,
        "尋晚": 1, "昨晚": 1, "琴晚": 1, "噚晚": 1, "昨日": 1, "琴日": 1, "噚日": 1, "前日": 1,
        "上個禮拜": 7, "上個星期": 7, "上禮拜": 7,
        "上兩日": 2, "上兩三日": 3,
    }
    FUTURE_MARKERS = {
        "聽日": 1, "听日": 1, "明天": 1, "明日": 1,
        "聽朝": 1, "听朝": 1, "明早": 1,
        "後日": 2, "后天": 2,
        "大後日": 3, "大后天": 3,
        "下個禮拜": -7, "下個星期": -7,
    }

    for marker, days in PAST_MARKERS.items():
        if marker in value:
            shift_days = days
            break
    else:
        for marker, days in FUTURE_MARKERS.items():
            if marker in value:
                shift_days = -days
                break

    if shift_days == 0:
        return None

    return (now_utc - timedelta(days=shift_days)).astimezone(timezone.utc)


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

    def infer_observed_at(self, text: str, now=None) -> Optional[datetime]:
        return infer_observed_at_from_text(text, now)
