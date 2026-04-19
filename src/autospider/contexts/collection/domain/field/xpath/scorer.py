from __future__ import annotations

from autospider.contexts.collection.domain.field.xpath.matcher import xpath_similarity
from autospider.contexts.collection.domain.field.xpath.normalizer import strip_indexes


def xpath_stability_score(xpaths: list[str]) -> float:
    normalized = [strip_indexes(item) for item in xpaths if strip_indexes(item)]
    if not normalized:
        return 0.0
    if len(normalized) == 1:
        return 1.0
    scores: list[float] = []
    for index, xpath in enumerate(normalized):
        for other in normalized[index + 1 :]:
            scores.append(xpath_similarity(xpath, other))
    return sum(scores) / len(scores) if scores else 1.0
