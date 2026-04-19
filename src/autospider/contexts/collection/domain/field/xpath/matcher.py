from __future__ import annotations

from autospider.contexts.collection.domain.field.xpath.normalizer import strip_indexes


def xpath_similarity(left: str, right: str) -> float:
    normalized_left = strip_indexes(left)
    normalized_right = strip_indexes(right)
    if not normalized_left or not normalized_right:
        return 0.0
    if normalized_left == normalized_right:
        return 1.0
    left_parts = normalized_left.split("/")
    right_parts = normalized_right.split("/")
    matches = sum(1 for a, b in zip(left_parts, right_parts) if a == b)
    longest = max(len(left_parts), len(right_parts))
    return matches / longest if longest else 0.0
