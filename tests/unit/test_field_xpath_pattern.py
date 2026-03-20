import asyncio

from autospider.field.models import FieldExtractionResult, PageExtractionRecord
from autospider.field.xpath_pattern import FieldXPathExtractor


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


def test_extract_common_pattern_uses_majority_normalized_xpath():
    extractor = FieldXPathExtractor()
    records = [
        _record("https://example.com/1", "A", '/html/body/div[1]/ul/li[1]/span'),
        _record("https://example.com/2", "B", '/html/body/div[2]/ul/li[3]/span'),
        _record("https://example.com/3", "C", '/html/body/div[4]/ul/li[9]/span'),
    ]

    result = asyncio.run(extractor.extract_common_pattern(records, "title"))

    assert result is not None
    assert result.xpath_pattern == '/html/body/div/ul/li/span'
    assert result.fallback_xpaths == []
    assert result.confidence == 1.0


def test_extract_common_pattern_returns_none_when_support_rate_too_low():
    extractor = FieldXPathExtractor()
    records = [
        _record("https://example.com/1", "A", '/html/body/div[1]/span'),
        _record("https://example.com/2", "B", '/html/body/main/section[2]/span'),
        _record("https://example.com/3", "C", '/html/body/article/header/h1'),
    ]

    result = asyncio.run(extractor.extract_common_pattern(records, "title"))

    assert result is None
