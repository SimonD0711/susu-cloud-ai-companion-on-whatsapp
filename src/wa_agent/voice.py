"""Voice message pipeline — TTS generation and WhatsApp delivery."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from src.ai.config import AIConfig
from src.ai.tts.minimax import MiniMaxTTS
from src.wa_agent.whatsapp import upload_whatsapp_media, send_whatsapp_audio


def generate_and_send_voice_reply(
    conn,
    wa_id: str,
    text: str,
    voice_id: str = "Cantonese_CuteGirl",
    config: Optional[AIConfig] = None,
) -> bool:
    """
    Convert text to speech and send as WhatsApp audio message.

    Args:
        conn: SQLite connection
        wa_id: WhatsApp recipient ID
        text: Text to convert to speech
        voice_id: MiniMax voice ID
        config: AIConfig instance (uses default if not provided)

    Returns:
        True if message was sent successfully, False otherwise.
    """
    config = config or AIConfig()
    audio_path = f"/tmp/susu_voice_{int(datetime.now(timezone.utc).timestamp() * 1000)}.mp3"

    tts = MiniMaxTTS(config)
    saved = tts.speak(text, voice_id=voice_id, output_path=audio_path)
    if not saved:
        return False

    media_id = upload_whatsapp_media(saved, mime_type="audio/mpeg")
    if not media_id:
        return False

    result = send_whatsapp_audio(wa_id, media_id)
    try:
        os.remove(audio_path)
    except Exception:
        pass
    return bool(result.get("messages") and result["messages"][0].get("id"))
