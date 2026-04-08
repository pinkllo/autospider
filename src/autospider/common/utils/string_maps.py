from __future__ import annotations

from typing import Any


def normalize_string_map(raw: object, *, drop_empty: bool = True) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in dict(raw or {}).items():
        text_key = str(key or "").strip()
        if not text_key:
            continue
        if isinstance(value, bool):
            text_value = "true" if value else "false"
        else:
            text_value = str(value or "").strip()
        if drop_empty and not text_value:
            continue
        normalized[text_key] = text_value
    return normalized
