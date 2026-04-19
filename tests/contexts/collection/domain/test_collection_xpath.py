from __future__ import annotations

from autospider.contexts.collection.domain import (
    build_xpath_fallback_chain,
    normalize_xpath,
    strip_indexes,
    xpath_similarity,
    xpath_stability_score,
)


def test_normalize_and_strip_indexes() -> None:
    xpath = " //div / ul/li[2]/a[1] "

    assert normalize_xpath(xpath) == "//div/ul/li[2]/a[1]"
    assert strip_indexes(xpath) == "//div/ul/li/a"


def test_xpath_similarity_and_stability_score() -> None:
    left = "//div/ul/li[1]/a"
    right = "//div/ul/li[2]/a"
    third = "//div/ul/li[3]/a"

    assert xpath_similarity(left, right) == 1.0
    assert xpath_stability_score([left, right, third]) == 1.0


def test_build_xpath_fallback_chain_reduces_depth() -> None:
    chain = build_xpath_fallback_chain("//div/ul/li/a/span")

    assert chain[0] == "//div/ul/li/a/span"
    assert "//div/ul/li/a" in chain
