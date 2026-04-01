"""Unified LLM entry point — manages providers and provides fallback."""

from __future__ import annotations

from typing import Optional

from src.ai.base import LLMMessage, LLMProvider, LLMResponse
from src.ai.config import AIConfig
from src.ai.llm.relay import RelayProvider, LLMError


class LLMManager:
    """
    Unified LLM interface.
    
    usage:
        config = AIConfig()
        manager = LLMManager(config)
        resp = manager.chat([LLMMessage(role="user", content="你好")])
        print(resp.content)
    """

    def __init__(self, config: Optional[AIConfig] = None):
        self.config = config or AIConfig()
        self.providers = {
            "relay": RelayProvider(self.config),
        }

    def chat(
        self,
        messages: list[LLMMessage],
        *,
        model: Optional[str] = None,
        temperature: float = 0.8,
        max_tokens: int = 200,
        provider: str = "relay",
    ) -> LLMResponse:
        """
        Unified chat interface.
        
        Args:
            messages: List of LLMMessage objects.
            model: Model name. If None, uses provider default.
            temperature: Sampling temperature.
            max_tokens: Max tokens to generate.
            provider: Which provider to use. Default: "relay".
        """
        p = self.providers.get(provider)
        if not p:
            raise ValueError(f"Unknown provider: {provider}")
        return p.chat(messages, model=model, temperature=temperature, max_tokens=max_tokens)

    def chat_text(
        self,
        messages: list[LLMMessage],
        *,
        model: Optional[str] = None,
        temperature: float = 0.8,
        max_tokens: int = 200,
        provider: str = "relay",
    ) -> str:
        """Convenience: returns just the text string."""
        return self.chat(
            messages, model=model, temperature=temperature, max_tokens=max_tokens, provider=provider
        ).content

    def chat_with_fallback(
        self,
        messages: list[LLMMessage],
        *,
        primary_model: Optional[str] = None,
        fallback_model: Optional[str] = None,
        temperature: float = 0.8,
        max_tokens: int = 200,
    ) -> LLMResponse:
        """
        Try primary model, fall back to fallback model on failure.
        """
        p = self.providers["relay"]
        try:
            return p.chat(
                messages,
                model=primary_model or self.config.RELAY_MODEL,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except LLMError:
            if fallback_model:
                return p.chat(
                    messages,
                    model=fallback_model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            raise
