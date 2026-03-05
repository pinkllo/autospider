from __future__ import annotations

import asyncio
from types import SimpleNamespace

from autospider.field.batch_xpath_extractor import BatchXPathExtractor
from autospider.field.models import FieldExtractionResult, PageExtractionRecord


class _DummyLocator:
    pass


class _DummyPage:
    def __init__(self) -> None:
        self.url = "https://example.com/detail"

    def locator(self, _selector: str) -> _DummyLocator:
        return _DummyLocator()


class _FakeExploreSuccess:
    def __init__(self, page, fields, output_dir, max_nav_steps):
        self.page = page
        self.fields = fields
        self.output_dir = output_dir
        self.max_nav_steps = max_nav_steps
        self.field_decider = SimpleNamespace(page=page)
        self.action_executor = SimpleNamespace(page=page)

    async def extract_from_url(self, url: str) -> PageExtractionRecord:
        return PageExtractionRecord(
            url=url,
            fields=[
                FieldExtractionResult(
                    field_name=field.name,
                    value=f"探索值-{field.name}",
                    confidence=0.86,
                    extraction_method="llm",
                )
                for field in self.fields
            ],
            success=True,
        )


class _FakeExploreFail(_FakeExploreSuccess):
    async def extract_from_url(self, url: str) -> PageExtractionRecord:
        raise RuntimeError("explore boom")


def test_auto_upgrade_to_explore_after_salvage_failure(monkeypatch):
    monkeypatch.setattr(
        "autospider.field.batch_xpath_extractor.FieldExtractor",
        _FakeExploreSuccess,
    )
    async def _run() -> None:
        extractor = BatchXPathExtractor(
            page=_DummyPage(),
            fields_config=[
                {
                    "name": "title",
                    "description": "标题",
                    "required": True,
                    "data_type": "text",
                    "xpath": "//*[@id='title']",
                }
            ],
            output_dir="output/test_batch_xpath_explore_upgrade",
        )

        async def _noop(*args, **kwargs):
            return None

        async def _missing_value(*args, **kwargs):
            return None, "XPath 未返回内容"

        monkeypatch.setattr(extractor, "_safe_goto", _noop)
        monkeypatch.setattr(extractor, "_ensure_page", _noop)
        monkeypatch.setattr(extractor, "_extract_field_value", _missing_value)
        monkeypatch.setattr(extractor, "_salvage_required_fields", _noop)

        record = await extractor._extract_from_url("https://example.com/detail/1")

        assert record.success is True
        title = record.get_field("title")
        assert title is not None
        assert title.value == "探索值-title"
        assert title.extraction_method == "explore_upgrade"
        assert title.salvage_reason == "explore_upgrade_succeeded"
        assert title.error is None

    asyncio.run(_run())


def test_auto_upgrade_to_explore_keeps_failure_when_explore_errors(monkeypatch):
    monkeypatch.setattr(
        "autospider.field.batch_xpath_extractor.FieldExtractor",
        _FakeExploreFail,
    )
    async def _run() -> None:
        extractor = BatchXPathExtractor(
            page=_DummyPage(),
            fields_config=[
                {
                    "name": "title",
                    "description": "标题",
                    "required": True,
                    "data_type": "text",
                    "xpath": "//*[@id='title']",
                }
            ],
            output_dir="output/test_batch_xpath_explore_upgrade",
        )

        async def _noop(*args, **kwargs):
            return None

        async def _missing_value(*args, **kwargs):
            return None, "XPath 未返回内容"

        monkeypatch.setattr(extractor, "_safe_goto", _noop)
        monkeypatch.setattr(extractor, "_ensure_page", _noop)
        monkeypatch.setattr(extractor, "_extract_field_value", _missing_value)
        monkeypatch.setattr(extractor, "_salvage_required_fields", _noop)

        record = await extractor._extract_from_url("https://example.com/detail/2")

        assert record.success is False
        title = record.get_field("title")
        assert title is not None
        assert "explore_upgrade_failed" in str(title.error)

    asyncio.run(_run())
