from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from autospider.domain.fields import FieldDefinition
from autospider.field.field_extractor import FieldExtractor
from autospider.field.xpath_helpers import build_xpath_fallback_chain, xpath_stability_score
from autospider.field.xpath_pattern import FieldXPathExtractor


def test_field_xpath_extractor_uses_canonical_stability_score_for_ranking():
    extractor = FieldXPathExtractor()
    candidates = [
        "//*[@data-id='notice-title']",
        "//*[@id='notice-title']",
        "//div[7]/span[2]",
    ]
    order_map = {xpath: idx for idx, xpath in enumerate(candidates)}
    ranked = extractor._rank_exact_xpaths(candidates)
    expected = sorted(
        candidates,
        key=lambda xpath: (
            -candidates.count(xpath),
            -xpath_stability_score(xpath),
            order_map[xpath],
        ),
    )

    assert ranked == expected


def test_field_extractor_uses_canonical_stability_score_for_selection(monkeypatch, tmp_path):
    monkeypatch.setattr(FieldExtractor, "_initialize_components", lambda self: None)
    extractor = FieldExtractor(
        page=SimpleNamespace(),
        fields=[],
        output_dir=str(tmp_path),
    )

    async def _always_verify(*, xpath, field, expected_value):
        _ = (xpath, field, expected_value)
        return True

    monkeypatch.setattr(extractor, "_verify_xpath", _always_verify)
    candidates = [
        "//*[@data-id='notice-title']",
        "//*[@id='notice-title']",
        "//div[7]/span[2]",
    ]
    selected = asyncio.run(
        extractor._select_best_verified_xpath(
            candidates=candidates,
            field=FieldDefinition(name="title", description="标题"),
            expected_value="公告标题",
        )
    )

    assert selected == max(candidates, key=xpath_stability_score)


def test_xpath_modules_only_use_canonical_helper_entries():
    project_root = Path(__file__).resolve().parents[2]
    pattern_source = (project_root / "src" / "autospider" / "field" / "xpath_pattern.py").read_text(
        encoding="utf-8"
    )
    extractor_source = (
        project_root / "src" / "autospider" / "field" / "field_extractor.py"
    ).read_text(encoding="utf-8")

    assert "def _generate_common_pattern_with_llm(" not in pattern_source
    assert "def _build_xpath_fallback_chain(" not in pattern_source
    assert "def _is_semantically_valid(" not in pattern_source
    assert "def _xpath_stability_score(" not in extractor_source
    assert "from .xpath_helpers import xpath_stability_score" in extractor_source
    assert build_xpath_fallback_chain("//a | //b", ["//c", "//b"]) == ["//a", "//b", "//c"]
