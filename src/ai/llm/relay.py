"""Relay LLM provider — OpenAI-compatible endpoint at https://apiapipp.com/v1."""

from __future__ import annotations

import json
import time
from typing import Optional

from src.ai.base import LLMMessage, LLMProvider, LLMResponse
from src.ai.config import AIConfig


class LLMError(Exception):
    """Base exception for LLM errors."""
    pass


class HTTPError(LLMError):
    def __init__(self, code: int, message: str):
        super().__init__(f"HTTP {code}: {message}")
        self.code = code


_RETRYABLE_CODES = {408, 409, 425, 429, 500, 502, 503, 504}


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, HTTPError):
        return exc.code in _RETRYABLE_CODES
    return True


class RelayProvider(LLMProvider):
    """Provider for the custom OpenAI-compatible relay endpoint."""

    def __init__(self, config: AIConfig):
        self.config = config

    def _do_request(
        self,
        model: str,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> dict:
        try:
            import urllib.request
        except ImportError as e:
            raise LLMError("urllib.request not available") from e

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        url = f"{self.config.RELAY_BASE_URL.rstrip('/')}/chat/completions"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {self.config.RELAY_API_KEY}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=40) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise HTTPError(e.code, body) from e
        except urllib.error.URLError as e:
            raise LLMError(f"URL error: {e.reason}") from e

    def _call(
        self,
        model: str,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        raw = self._do_request(model, messages, temperature, max_tokens)
        choices = (raw.get("choices") or [{}])
        content = ((choices[0] or {}).get("message") or {}).get("content", "").strip()
        return LLMResponse(content=content, model=model, raw=raw)

    def chat(
        self,
        messages: list[LLMMessage],
        *,
        model: Optional[str] = None,
        temperature: float = 0.8,
        max_tokens: int = 200,
        retry_count: Optional[int] = None,
    ) -> LLMResponse:
        """
        Send a chat completion request via the relay API.

        Args:
            messages: List of LLMMessage objects (role + content).
            model: Model name. Defaults to RELAY_MODEL from config.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.
            retry_count: Number of retries on failure. Defaults to RELAY_RETRY_COUNT.
        """
        model = model or self.config.RELAY_MODEL
        retry_count = retry_count if retry_count is not None else self.config.RELAY_RETRY_COUNT
        retry_count = max(retry_count, 1)

        backoff = self.config.RELAY_RETRY_BACKOFF_SECONDS

        messages_dicts = [{"role": m.role, "content": m.content} for m in messages]
        errors = []

        for attempt in range(retry_count):
            try:
                return self._call(model, messages_dicts, temperature, max_tokens)
            except Exception as exc:
                errors.append(exc)
                if attempt >= retry_count - 1 or not _is_retryable(exc):
                    break
                time.sleep(max(backoff, 0.1) * (attempt + 1))

        if errors:
            raise errors[-1]
        return LLMResponse(content="", model=model)
