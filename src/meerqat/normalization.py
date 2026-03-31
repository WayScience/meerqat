"""Identifier normalization helpers."""

from __future__ import annotations

import re


def normalize_identifier(value: str | None) -> str:
    """Normalize dataset identifiers for matching."""
    if value is None:
        return ""
    compact = re.sub(r"[^a-zA-Z0-9]+", "", value)
    return compact.lower()
