from __future__ import annotations

import re


def clean_xpath(value: str) -> str:
    xpath = value.strip()
    if xpath.lower().startswith("xpath="):
        xpath = xpath[6:].strip()
    if xpath.startswith(("'", '"')) and xpath.endswith(("'", '"')):
        xpath = xpath[1:-1].strip()
    return xpath if xpath.startswith("/") else ""


def normalize_xpath_for_comparison(xpath: str) -> str:
    return re.sub(r"\[\d+\]", "", xpath or "")


def normalize_xpath_majority_key(xpath: str) -> str:
    value = clean_xpath(xpath)
    if not value:
        return ""
    value = normalize_xpath_for_comparison(value)
    return re.sub(r"\s+", "", value)


def xpath_stability_score(xpath: str) -> float:
    value = (xpath or "").strip()
    if not value:
        return -10.0

    lower = value.lower()
    score = 0.0

    if "@id=" in lower:
        score += 3.0
    if "@data-" in lower:
        score += 1.8
    if "@class" in lower:
        score += 0.8
    if lower.startswith("//*[@id="):
        score += 0.5

    numeric_index_count = len(re.findall(r"\[\d+\]", value))
    score -= numeric_index_count * 0.2

    depth = value.count("/")
    if depth > 10:
        score -= (depth - 10) * 0.08

    volatile_tokens = ("fixed", "sticky", "float", "popup", "modal", "dialog", "mask")
    if any(token in lower for token in volatile_tokens):
        score -= 1.8

    if "|" in value:
        score -= 0.6

    return score


def build_xpath_fallback_chain(
    xpath_pattern: str,
    fallback_xpaths: list[str] | None = None,
) -> list[str]:
    primary = (xpath_pattern or "").strip()
    if not primary:
        return []

    chain: list[str] = []
    if " | " in primary:
        chain.extend(part.strip() for part in primary.split(" | ") if part.strip())
    else:
        chain.append(primary)

    for xpath in fallback_xpaths or []:
        value = str(xpath or "").strip()
        if value and value not in chain:
            chain.append(value)

    return [xpath for xpath in chain if xpath.startswith("/")]
