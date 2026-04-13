"""Shared normalization helpers for structured grouping semantics."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

_SEMANTIC_INPUT_KEYS = (
    "group_by",
    "per_group_target_count",
    "total_target_count",
    "category_discovery_mode",
    "requested_categories",
    "category_examples",
)


def normalize_positive_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def normalize_string_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple, set)):
        items = value
    else:
        items = [value]
    normalized: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if text:
            normalized.append(text)
    return normalized


def normalize_group_by(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in {"none", "category"} else "none"


def normalize_category_discovery_mode(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in {"auto", "manual"} else "auto"


def normalize_grouping_semantics(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    raw = dict(payload or {})
    group_by = normalize_group_by(raw.get("group_by"))
    per_group_target_count = normalize_positive_int(raw.get("per_group_target_count"))
    total_target_count = normalize_positive_int(raw.get("total_target_count"))
    category_discovery_mode = normalize_category_discovery_mode(
        raw.get("category_discovery_mode")
    )
    requested_categories = normalize_string_list(raw.get("requested_categories"))
    category_examples = normalize_string_list(raw.get("category_examples"))

    if group_by == "none":
        return {
            "group_by": "none",
            "per_group_target_count": None,
            "total_target_count": total_target_count,
            "category_discovery_mode": "auto",
            "requested_categories": [],
            "category_examples": [],
        }

    if category_discovery_mode == "manual" and not requested_categories:
        category_discovery_mode = "auto"
    if category_discovery_mode == "auto":
        requested_categories = []

    return {
        "group_by": group_by,
        "per_group_target_count": per_group_target_count,
        "total_target_count": total_target_count,
        "category_discovery_mode": category_discovery_mode,
        "requested_categories": requested_categories,
        "category_examples": category_examples,
    }


def normalize_semantic_labels(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple, set)):
        items = value
    else:
        items = [value]
    labels = {
        str(item or "").strip()
        for item in items
        if str(item or "").strip()
    }
    return sorted(labels)


def normalize_field_names(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple, set)):
        items = value
    else:
        items = [value]
    names: list[str] = []
    for item in items:
        candidate = item.get("name") if isinstance(item, Mapping) else item
        text = str(candidate or "").strip()
        if text:
            names.append(text)
    return normalize_semantic_labels(names)


def build_normalized_strategy_payload(
    payload: Mapping[str, Any] | None,
    *,
    fallback_field_names: Any = None,
) -> dict[str, Any]:
    raw = dict(payload or {})
    grouping = normalize_grouping_semantics(raw)
    explicit_fields = normalize_field_names(raw.get("field_names"))
    field_names = explicit_fields or normalize_field_names(fallback_field_names)
    return {
        "group_by": grouping["group_by"],
        "per_group_target_count": grouping["per_group_target_count"],
        "total_target_count": grouping["total_target_count"],
        "category_discovery_mode": grouping["category_discovery_mode"],
        "requested_categories": normalize_semantic_labels(grouping["requested_categories"]),
        "category_examples": normalize_semantic_labels(grouping["category_examples"]),
        "field_names": field_names,
    }


def has_semantic_signature_inputs(
    payload: Mapping[str, Any] | None,
    *,
    fallback_field_names: Any = None,
) -> bool:
    raw = dict(payload or {})
    if normalize_field_names(raw.get("field_names")):
        return True
    if normalize_field_names(fallback_field_names):
        return True
    return any(raw.get(key) not in (None, "", [], {}) for key in _SEMANTIC_INPUT_KEYS)


def build_semantic_signature_from_payload(
    payload: Mapping[str, Any] | None,
    *,
    fallback_field_names: Any = None,
) -> str:
    normalized = build_normalized_strategy_payload(
        payload,
        fallback_field_names=fallback_field_names,
    )
    raw = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
