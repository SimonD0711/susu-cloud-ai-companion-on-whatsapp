"""Utility functions for wa_agent."""

from __future__ import annotations

import os
import re
from pathlib import Path


def getenv(key: str, default: str = "", required: bool = False) -> str:
    """Get environment variable with optional default and required flag."""
    value = os.environ.get(key, default)
    if required and not value:
        raise ValueError(f"Required environment variable {key} is not set")
    return value


def parse_bool(value: str) -> bool:
    """Parse a boolean value from environment variable string."""
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_int(value: str, default: int = 0, minimum: int | None = None, maximum: int | None = None) -> int:
    """Parse an integer value from environment variable string."""
    try:
        parsed = int(value.strip())
    except (ValueError, TypeError):
        parsed = default
    if minimum is not None:
        parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def parse_float(value: str, default: float = 0.0) -> float:
    """Parse a float value from environment variable string."""
    try:
        return float(value.strip())
    except (ValueError, TypeError):
        return default


def ensure_dir(path: str | Path) -> Path:
    """Ensure a directory exists, creating it if necessary."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def clean_text(text: str) -> str:
    """Remove zero-width characters and normalize whitespace."""
    return re.sub(r"\s+", " ", str(text or "").strip())


def normalize_key(text: str) -> str:
    """Create a normalized key for deduplication."""
    cleaned = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]", "", text.lower())
    return cleaned[:100]
