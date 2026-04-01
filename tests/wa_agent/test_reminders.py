"""Tests for src.wa_agent.reminders."""

import pytest
from unittest.mock import patch, MagicMock
from src.wa_agent.reminders import (
    detect_reminder,
    parse_reminder_from_text,
    fire_reminder,
    run_reminder_scan_once,
    _is_reminder_task,
    _parse_reminder,
)


def test_detect_reminder_yes(monkeypatch):
    """Test that detect_reminder returns True when AI says YES."""
    with patch("src.wa_agent.reminders._is_reminder_task") as mock:
        mock.return_value = True
        assert detect_reminder("6點提醒我開會") is True


def test_detect_reminder_no(monkeypatch):
    """Test that detect_reminder returns False when AI says NO."""
    with patch("src.wa_agent.reminders._is_reminder_task") as mock:
        mock.return_value = False
        assert detect_reminder("今日天氣好") is False


def test_parse_reminder_from_text(monkeypatch):
    """Test parse_reminder_from_text delegates to _parse_reminder."""
    with patch("src.wa_agent.reminders._parse_reminder") as mock:
        mock.return_value = ("2026-04-01T18:00:00+08:00", "開會")
        result = parse_reminder_from_text("85298765432", "6點提醒我開會")
        assert result == ("2026-04-01T18:00:00+08:00", "開會")


def test_fire_reminder_success(monkeypatch):
    """Test fire_reminder sends WhatsApp message."""
    with patch("src.wa_agent.reminders._generate_model_text") as mock_gen:
        mock_gen.return_value = "記住喇～開會啊！"
        with patch("src.wa_agent.reminders.send_whatsapp_text") as mock_send:
            mock_send.return_value = {"messages": [{"id": "msg_123"}]}
            result = fire_reminder("85298765432", "開會")
            assert result is True
            mock_gen.assert_called_once()
            mock_send.assert_called_once_with("85298765432", "記住喇～開會啊！")


def test_fire_reminder_fallback(monkeypatch):
    """Test fire_reminder uses fallback when AI fails."""
    with patch("src.wa_agent.reminders._generate_model_text") as mock_gen:
        mock_gen.side_effect = Exception("AI failed")
        with patch("src.wa_agent.reminders.send_whatsapp_text") as mock_send:
            mock_send.return_value = {"messages": [{"id": "msg_123"}]}
            result = fire_reminder("85298765432", "開會")
            assert result is True
            mock_send.assert_called_once_with("85298765432", "記住喇～ 開會 啊！")


def test_run_reminder_scan_once_no_db(monkeypatch):
    """Test run_reminder_scan_once handles missing DB gracefully."""
    with patch("src.wa_agent.db.MemoryDB") as mock_db:
        mock_db.side_effect = Exception("DB error")
        result = run_reminder_scan_once()
        assert result["ok"] is False
        assert result["status"] == "error"
