import asyncio

import pytest

from autospider.field import xpath_pattern as xpath_pattern_module
from autospider.field.models import FieldExtractionResult, PageExtractionRecord
from autospider.field.xpath_pattern import FieldXPathExtractor, validate_xpath_pattern


def _record(url: str, value: str | None, xpath: str | None) -> PageExtractionRecord:
    return PageExtractionRecord(
        url=url,
        fields=[
            FieldExtractionResult(
                field_name="title",
                value=value,
                xpath=xpath,
            )
        ],
        success=True,
    )


def test_extract_common_pattern_keeps_exact_xpath_and_builds_fallback_chain():
    extractor = FieldXPathExtractor()
    records = [
        _record("https://example.com/1", "A", '/html/body/div[1]/ul/li[1]/span'),
        _record("https://example.com/2", "B", '/html/body/div[2]/ul/li[3]/span'),
        _record("https://example.com/3", "C", '/html/body/div[4]/ul/li[9]/span'),
    ]

    result = asyncio.run(extractor.extract_common_pattern(records, "title"))

    assert result is not None
    assert result.xpath_pattern == '/html/body/div[1]/ul/li[1]/span'
    assert result.fallback_xpaths == [
        '/html/body/div[2]/ul/li[3]/span',
        '/html/body/div[4]/ul/li[9]/span',
    ]
    assert result.confidence == pytest.approx(1 / 3, rel=1e-6)


def test_extract_common_pattern_prefers_dominant_exact_xpath():
    extractor = FieldXPathExtractor()
    records = [
        _record("https://example.com/1", "A", '//*[@id="app"]/main/table/tr[1]/td/span'),
        _record("https://example.com/2", "B", '//*[@id="app"]/main/table/tr[1]/td/span'),
        _record("https://example.com/3", "C", '//*[@id="app"]/article/section/ul/li[1]/span'),
    ]

    result = asyncio.run(extractor.extract_common_pattern(records, "title"))

    assert result is not None
    assert result.xpath_pattern == '//*[@id="app"]/main/table/tr[1]/td/span'
    assert result.fallback_xpaths == ['//*[@id="app"]/article/section/ul/li[1]/span']
    assert result.confidence == pytest.approx(2 / 3, rel=1e-6)


def test_extract_common_pattern_keeps_multiple_exact_xpaths_for_distinct_layouts():
    extractor = FieldXPathExtractor()
    records = [
        _record("https://example.com/1", "A", '/html/body/div[1]/span'),
        _record("https://example.com/2", "B", '/html/body/main/section[2]/span'),
        _record("https://example.com/3", "C", '/html/body/article/header/h1'),
    ]

    result = asyncio.run(extractor.extract_common_pattern(records, "title"))

    assert result is not None
    assert result.xpath_pattern == '/html/body/article/header/h1'
    assert result.fallback_xpaths == [
        '/html/body/div[1]/span',
        '/html/body/main/section[2]/span',
    ]
    assert result.confidence == pytest.approx(1 / 3, rel=1e-6)


class _FakeLocator:
    pass


class _FakePage:
    async def goto(self, *args, **kwargs):
        return None

    def locator(self, query: str):
        return _FakeLocator()


@pytest.mark.asyncio
async def test_validate_xpath_pattern_rejects_multiple_distinct_values(monkeypatch):
    async def _noop_page_settle(page):
        return None

    async def _two_matches(page, locator):
        return 2

    async def _distinct_values(**kwargs):
        return ["项目A", "项目B"]

    monkeypatch.setattr(xpath_pattern_module, "_wait_for_page_settle", _noop_page_settle)
    monkeypatch.setattr(xpath_pattern_module, "_wait_for_locator_count", _two_matches)
    monkeypatch.setattr(xpath_pattern_module, "_collect_unique_values_with_retry", _distinct_values)

    success, value, trace = await validate_xpath_pattern(
        page=_FakePage(),
        url="https://example.com/detail/1",
        xpath_pattern='//*[@id="title"]',
        data_type="text",
        field_name="project_name",
    )

    assert success is False
    assert value is None
    assert trace["attempts"][0]["reason"] == "multiple_distinct_values"
    assert trace["failure_reason"] == "all_candidates_failed"
