"""Helpers for extracting normalized token usage from LLM payloads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def extract_token_usage(payload: Any) -> dict[str, int] | None:
    """Extract normalized token usage from a LangChain/OpenAI payload."""
    for candidate in _iter_candidates(payload):
        normalized = _normalize_usage(candidate)
        if normalized is not None:
            return normalized
    return None


def _iter_candidates(payload: Any) -> list[Any]:
    candidates: list[Any] = []
    queue = [payload]
    seen: set[int] = set()
    while queue:
        current = queue.pop(0)
        if current is None:
            continue
        marker = id(current)
        if marker in seen:
            continue
        seen.add(marker)
        candidates.append(current)
        queue.extend(_expand_value(current))
    return candidates


def _expand_value(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        items: list[Any] = []
        for key in ("usage_metadata", "token_usage", "usage", "response_metadata", "additional_kwargs"):
            if key in value:
                items.append(value.get(key))
        items.extend(value.values())
        return items
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    if hasattr(value, "usage_metadata"):
        return [
            getattr(value, "usage_metadata", None),
            getattr(value, "response_metadata", None),
            getattr(value, "additional_kwargs", None),
            getattr(value, "content", None),
        ]
    if hasattr(value, "model_dump") and callable(value.model_dump):
        try:
            return [value.model_dump(mode="python")]
        except Exception:
            return []
    return []


def _normalize_usage(value: Any) -> dict[str, int] | None:
    if not isinstance(value, Mapping):
        return None
    raw = dict(value)
    prompt = _as_int(raw.get("prompt_tokens"), raw.get("input_tokens"))
    completion = _as_int(raw.get("completion_tokens"), raw.get("output_tokens"))
    total = _as_int(raw.get("total_tokens"))
    if total is None and prompt is not None and completion is not None:
        total = prompt + completion
    if prompt is None and completion is None and total is None:
        return None
    return {
        "prompt_tokens": max(0, int(prompt or 0)),
        "completion_tokens": max(0, int(completion or 0)),
        "total_tokens": max(0, int(total or 0)),
    }


def _as_int(*values: Any) -> int | None:
    for value in values:
        if value is None or value == "":
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None

