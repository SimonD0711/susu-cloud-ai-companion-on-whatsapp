"""Abstract base classes for AI providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class LLMMessage:
    role: str
    content: str


@dataclass
class LLMResponse:
    content: str
    model: str
    raw: Optional[dict] = None


class LLMProvider(ABC):
    """Abstract base class for all LLM providers."""

    @abstractmethod
    def chat(
        self,
        messages: list[LLMMessage],
        *,
        model: Optional[str] = None,
        temperature: float = 0.8,
        max_tokens: int = 200,
    ) -> LLMResponse:
        """Send a chat completion request and return the response content."""
        ...

    def chat_text(
        self,
        messages: list[LLMMessage],
        *,
        model: Optional[str] = None,
        temperature: float = 0.8,
        max_tokens: int = 200,
    ) -> str:
        """Convenience method that returns just the text string."""
        return self.chat(messages, model=model, temperature=temperature, max_tokens=max_tokens).content
