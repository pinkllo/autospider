from __future__ import annotations

from autospider.contexts.collection.domain.field.xpath.normalizer import normalize_xpath


def build_xpath_fallback_chain(xpath: str) -> list[str]:
    normalized = normalize_xpath(xpath)
    if not normalized:
        return []
    parts = normalized.split("/")
    chain = [normalized]
    for end in range(len(parts) - 1, 2, -1):
        candidate = "/".join(parts[:end])
        if candidate and candidate not in chain:
            chain.append(candidate)
    return chain
