"""Tests for src.wa_agent.whatsapp."""

import pytest
from src.wa_agent.whatsapp import (
    parse_message_context,
    reset_contact_read_cycle,
    default_read_scheduler_state,
    send_whatsapp_text,
    send_whatsapp_mark_as_read,
    send_whatsapp_typing_indicator,
    upload_whatsapp_media,
    send_whatsapp_audio,
    send_whatsapp_reaction,
)


def test_default_read_scheduler_state():
    state = default_read_scheduler_state()
    assert state["delay_consumed"] is False
    assert state["pending_message_ids"] == []
    assert state["timer_running"] is False
    assert state["deadline_at"] == 0.0
    assert state["cycle_id"] == 0


def test_parse_message_context_empty():
    result = parse_message_context({})
    assert result["quoted_message_id"] == ""
    assert result["quoted_from"] == ""


def test_parse_message_context_with_context():
    payload = {
        "context": {
            "id": "msg_123",
            "from": "85298765432",
        }
    }
    result = parse_message_context(payload)
    assert result["quoted_message_id"] == "msg_123"
    assert result["quoted_from"] == "85298765432"


def test_parse_message_context_json_string():
    result = parse_message_context('{"context": {"id": "msg_456"}}')
    assert result["quoted_message_id"] == "msg_456"


def test_reset_contact_read_cycle():
    state = reset_contact_read_cycle("85298765432")
    assert state is None


def test_send_whatsapp_text_missing_credentials(monkeypatch):
    monkeypatch.delenv("WA_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("WA_PHONE_NUMBER_ID", raising=False)
    from src.wa_agent import whatsapp
    monkeypatch.setattr(whatsapp, "ACCESS_TOKEN", "")
    monkeypatch.setattr(whatsapp, "PHONE_NUMBER_ID", "")
    result = send_whatsapp_text("85298765432", "hello")
    assert result["ok"] is False
    assert "Missing" in result["detail"]
