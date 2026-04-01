"""MiniMax TTS provider."""

from __future__ import annotations

import json
import os
from typing import Optional

from src.ai.config import AIConfig


class TTSError(Exception):
    """TTS-related errors."""
    pass


class MiniMaxTTS:
    """MiniMax Text-to-Speech provider."""

    def __init__(self, config: AIConfig):
        self.config = config

    def speak(
        self,
        text: str,
        voice_id: Optional[str] = None,
        speed: float = 1.0,
        output_path: str = "/tmp/susu_voice.mp3",
    ) -> Optional[str]:
        """
        Generate speech from text using MiniMax API.

        Args:
            text: Text to synthesize.
            voice_id: Voice ID. Defaults to config.TTS_VOICE_ID.
            speed: Playback speed (0.5-2.0). Defaults to config.TTS_SPEED.
            output_path: Path to write MP3 file.

        Returns:
            Path to generated audio file, or None on failure.
        """
        if not text:
            return None
        if not self.config.MINIMAX_API_KEY:
            return None

        voice_id = voice_id or self.config.TTS_VOICE_ID
        speed = speed if speed else self.config.TTS_SPEED

        try:
            os.makedirs(os.path.dirname(output_path) or "/tmp", exist_ok=True)
        except Exception:
            pass

        payload = {
            "model": "speech-2.8-hd",
            "text": text,
            "voice_setting": {
                "voice_id": voice_id,
                "speed": speed,
                "vol": 1.0,
                "pitch": 0,
                "emotion": "happy",
            },
            "audio_setting": {
                "sample_rate": 32000,
                "bitrate": 128000,
                "format": "mp3",
                "channel": 1,
            },
            "language_boost": "Chinese,Yue",
        }

        try:
            import urllib.request
            url = f"{self.config.MINIMAX_BASE_URL}/t2a_v2"
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self.config.MINIMAX_API_KEY}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
            audio_hex = raw.get("data", {}).get("audio", "")
            if not audio_hex:
                return None
            audio_bytes = bytes.fromhex(audio_hex)
            with open(output_path, "wb") as f:
                f.write(audio_bytes)
            return output_path
        except Exception:
            return None
