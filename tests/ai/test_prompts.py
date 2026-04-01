"""Tests for src.ai.llm.prompts."""

import pytest
from src.ai.llm import prompts


def test_memory_extractor_prompt_not_empty():
    assert len(prompts.MEMORY_EXTRACTOR_PROMPT) > 50
    assert "JSON" in prompts.MEMORY_EXTRACTOR_PROMPT


def test_recent_memory_extractor_prompt_not_empty():
    assert len(prompts.RECENT_MEMORY_EXTRACTOR_PROMPT) > 20
    assert "within_24h" in prompts.RECENT_MEMORY_EXTRACTOR_PROMPT


def test_live_search_summarizer_prompt_contains_hints():
    assert "蘇蘇" in prompts.LIVE_SEARCH_SUMMARIZER_PROMPT
    assert "粵" in prompts.LIVE_SEARCH_SUMMARIZER_PROMPT or "廣東話" in prompts.LIVE_SEARCH_SUMMARIZER_PROMPT


def test_router_prompt_contains_required_fields():
    p = prompts.LIVE_SEARCH_ROUTER_PROMPT
    assert "should_search" in p
    assert "mode" in p


def test_system_persona_not_empty():
    assert len(prompts.SYSTEM_PERSONA) > 20
    assert "蘇蘇" in prompts.SYSTEM_PERSONA


def test_all_prompts_are_strings():
    for name in dir(prompts):
        if not name.startswith("_"):
            val = getattr(prompts, name)
            assert isinstance(val, str), f"{name} is not a string"
