"""Tests for src.wa_agent.memory."""

import pytest

from src.wa_agent.memory import (
    is_long_term_memory_candidate,
    is_recent_memory_candidate,
    normalize_key,
    normalize_recent_bucket,
    classify_recent_memory_bucket,
    MemoryManager,
    MEMORY_EXTRACTOR_PROMPT,
    RECENT_MEMORY_EXTRACTOR_PROMPT,
)


def test_is_long_term_memory_candidate_valid():
    assert is_long_term_memory_candidate("Simon喺香港讀書") is True
    assert is_long_term_memory_candidate("我最鍾意周杰倫") is True


def test_is_long_term_memory_candidate_too_short():
    assert is_long_term_memory_candidate("你好") is False
    assert is_long_term_memory_candidate("hi") is False


def test_is_long_term_memory_candidate_greetings():
    assert is_long_term_memory_candidate("早晨") is False
    assert is_long_term_memory_candidate("晚安") is False
    assert is_long_term_memory_candidate("Thank you") is False


def test_is_long_term_memory_candidate_too_long():
    assert is_long_term_memory_candidate("A" * 300) is False


def test_is_recent_memory_candidate_valid():
    assert is_recent_memory_candidate("今日約咗朋友") is True
    assert is_recent_memory_candidate("聽日考試") is True


def test_is_recent_memory_candidate_too_short():
    assert is_recent_memory_candidate("好") is False
    assert is_recent_memory_candidate("X") is False


def test_normalize_key():
    key = normalize_key("Simon 最鍾意周杰倫！?")
    assert len(key) <= 100
    assert key.islower() or not any(c.isalpha() for c in key)


def test_normalize_recent_bucket_within_24h():
    assert normalize_recent_bucket("within_24h") == "within_24h"
    assert normalize_recent_bucket("today") == "within_24h"
    assert normalize_recent_bucket("tonight") == "within_24h"


def test_normalize_recent_bucket_within_3d():
    assert normalize_recent_bucket("within_3d") == "within_3d"
    assert normalize_recent_bucket("") == "within_7d"


def test_normalize_recent_bucket_within_7d():
    assert normalize_recent_bucket("within_7d") == "within_7d"
    assert normalize_recent_bucket("unknown") == "within_7d"


def test_classify_recent_memory_bucket_24h():
    assert classify_recent_memory_bucket("今日約咗朋友") == "within_24h"
    assert classify_recent_memory_bucket("今晚去睇戲") == "within_24h"


def test_classify_recent_memory_bucket_3d():
    assert classify_recent_memory_bucket("尋晚睇咗個片") == "within_3d"
    assert classify_recent_memory_bucket("聽日考試") == "within_3d"


def test_classify_recent_memory_bucket_7d():
    assert classify_recent_memory_bucket("呢個星期要交功課") == "within_7d"
    assert classify_recent_memory_bucket("普通句子") == "within_7d"


def test_memory_extractor_prompt_not_empty():
    assert MEMORY_EXTRACTOR_PROMPT
    assert len(MEMORY_EXTRACTOR_PROMPT) > 50


def test_recent_memory_extractor_prompt_not_empty():
    assert RECENT_MEMORY_EXTRACTOR_PROMPT
    assert len(RECENT_MEMORY_EXTRACTOR_PROMPT) > 50


def test_memory_manager_has_extract_methods():
    from src.wa_agent.memory import MemoryManager
    manager = MemoryManager(None)
    assert hasattr(manager, "extract_and_save_long_term")
    assert hasattr(manager, "extract_and_save_session")
    assert hasattr(manager, "is_long_term_candidate")
    assert hasattr(manager, "is_recent_candidate")
    assert hasattr(manager, "normalize_key")
    assert hasattr(manager, "normalize_bucket")
    assert hasattr(manager, "classify_bucket")
