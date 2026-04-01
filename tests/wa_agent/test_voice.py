"""Tests for src.wa_agent.voice."""

import pytest
from unittest.mock import patch, MagicMock
from src.wa_agent.voice import generate_and_send_voice_reply


def test_generate_and_send_voice_reply_no_api_key(monkeypatch):
    """Test that voice reply fails gracefully when TTS API key is missing."""
    with patch("src.wa_agent.voice.MiniMaxTTS") as mock_tts:
        mock_tts.return_value.speak.return_value = None
        result = generate_and_send_voice_reply(
            conn=MagicMock(),
            wa_id="85298765432",
            text="hello",
        )
        assert result is False


def test_generate_and_send_voice_reply_tts_returns_path(monkeypatch, tmp_path):
    """Test that voice reply works when TTS returns a file path."""
    import importlib
    import src.ai.config
    monkeypatch.setenv("WA_MINIMAX_API_KEY", "test-key")
    importlib.reload(src.ai.config)

    audio_file = tmp_path / "test_voice.mp3"
    audio_file.write_bytes(b"fake audio data")

    with patch("src.wa_agent.voice.MiniMaxTTS") as mock_tts_class:
        mock_tts = MagicMock()
        mock_tts.speak.return_value = str(audio_file)
        mock_tts_class.return_value = mock_tts

        with patch("src.wa_agent.voice.upload_whatsapp_media") as mock_upload:
            mock_upload.return_value = "media_id_123"

            with patch("src.wa_agent.voice.send_whatsapp_audio") as mock_send:
                mock_send.return_value = {"messages": [{"id": "msg_id_123"}]}

                result = generate_and_send_voice_reply(
                    conn=MagicMock(),
                    wa_id="85298765432",
                    text="hello",
                )
                assert result is True
                mock_tts.speak.assert_called_once()
                mock_upload.assert_called_once()
                mock_send.assert_called_once_with("85298765432", "media_id_123")


def test_generate_and_send_voice_reply_upload_fails(monkeypatch, tmp_path):
    """Test that voice reply fails when media upload fails."""
    import importlib
    import src.ai.config
    monkeypatch.setenv("WA_MINIMAX_API_KEY", "test-key")
    importlib.reload(src.ai.config)

    audio_file = tmp_path / "test_voice.mp3"
    audio_file.write_bytes(b"fake audio data")

    with patch("src.wa_agent.voice.MiniMaxTTS") as mock_tts_class:
        mock_tts = MagicMock()
        mock_tts.speak.return_value = str(audio_file)
        mock_tts_class.return_value = mock_tts

        with patch("src.wa_agent.voice.upload_whatsapp_media") as mock_upload:
            mock_upload.return_value = None

            result = generate_and_send_voice_reply(
                conn=MagicMock(),
                wa_id="85298765432",
                text="hello",
            )
            assert result is False
