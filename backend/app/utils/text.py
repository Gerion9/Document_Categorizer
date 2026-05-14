"""Shared text normalization helpers."""

from __future__ import annotations

from typing import Any


def clean_text(value: Any) -> str:
    """Collapse whitespace and coerce empty-like values to an empty string."""
    return " ".join(str(value or "").split()).strip()
