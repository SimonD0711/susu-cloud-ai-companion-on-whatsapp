"""Groq Whisper transcription provider."""

from __future__ import annotations

import json
import time
from typing import Optional

from src.ai.config import AIConfig


class WhisperError(Exception):
    """Whisper transcription errors."""
    pass


class GroqWhisper:
    """Groq Whisper transcription provider using OpenAI-compatible API."""

    def __init__(self, config: AIConfig):
        self.config = config

    def transcribe(
        self,
        audio_bytes: bytes,
        mime_type: str = "audio/ogg",
        language: str = "yue",
    ) -> Optional[str]:
        """
        Transcribe audio using Groq Whisper API.

        Args:
            audio_bytes: Raw audio data.
            mime_type: Audio MIME type (e.g. "audio/ogg", "audio/mpeg").
            language: Language code for transcription.

        Returns:
            Transcribed text, or None on failure.
        """
        if not self.config.GROQ_API_KEY:
            return None

        boundary = "WhisperAudioBoundary" + str(int(time.time() * 1000))
        filename = "voice_message.ogg"
        if mime_type == "audio/mpeg":
            filename = "voice_message.mp3"

        def part(name: str, value: bytes, ctype: Optional[str] = None) -> bytes:
            ctype_line = f"Content-Type: {ctype}\r\n" if ctype else ""
            return (
                f"--{boundary}\r\n".encode()
                + f'Content-Disposition: form-data; name="{name}"'.encode()
                + (f'; filename="{filename}"'.encode() if name == "file" else b"")
                + f"\r\n{ctype_line}\r\n".encode()
                + value
                + b"\r\n"
            )

        body = b""
        body += part("file", audio_bytes, mime_type)
        body += part("model", b"whisper-large-v3")
        body += part("language", language.encode("utf-8"))
        body += f"--{boundary}--\r\n".encode()

        try:
            import urllib.request
            req = urllib.request.Request(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                data=body,
                headers={
                    "Authorization": f"Bearer {self.config.GROQ_API_KEY}",
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            text = (data.get("text") or "").strip()
            return text if text else None
        except Exception:
            return None
