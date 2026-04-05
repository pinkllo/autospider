from __future__ import annotations

import pytest

from autospider.domain.fields import FieldDefinition
from autospider.field import detail_page_worker as worker_module
from autospider.field.models import FieldExtractionResult, PageExtractionRecord


class _FakePage:
    pass


class _RegistryStub:
    def __init__(self, fields_config: list[dict]):
        self.fields_config = fields_config
        self.records: list[tuple[str, bool, str | None]] = []

    def build_fields_config(self, url: str, fields: list[FieldDefinition]) -> list[dict]:
        return list(self.fields_config)

    def record(self, url: str, record: PageExtractionRecord, *, success: bool) -> None:
        xpath = record.fields[0].xpath if record.fields else None
        self.records.append((url, success, xpath))


@pytest.mark.asyncio
async def test_detail_page_worker_falls_back_to_llm_and_records_xpath(monkeypatch):
    registry = _RegistryStub(
        [
            {
                "name": "project_name",
                "description": "项目名称",
                "xpath": '//*[@id="cached"]',
                "xpath_fallbacks": [],
                "required": True,
                "data_type": "text",
            }
        ]
    )

    class _FakeBatchXPathExtractor:
        def __init__(self, *args, **kwargs):
            return None

        async def _extract_from_url(self, url: str):
            return PageExtractionRecord(
                url=url,
                fields=[
                    FieldExtractionResult(
                        field_name="project_name",
                        xpath='//*[@id="cached"]',
                        error="XPath 未匹配到元素",
                    )
                ],
                success=False,
            )

    class _FakeFieldExtractor:
        def __init__(self, *args, **kwargs):
            return None

        async def extract_from_url(self, url: str):
            return PageExtractionRecord(
                url=url,
                fields=[
                    FieldExtractionResult(
                        field_name="project_name",
                        value="测试项目",
                        xpath='//*[@id="llm"]',
                    )
                ],
                success=True,
            )

    monkeypatch.setattr(worker_module, "BatchXPathExtractor", _FakeBatchXPathExtractor)
    monkeypatch.setattr(worker_module, "FieldExtractor", _FakeFieldExtractor)

    worker = worker_module.DetailPageWorker(
        page=_FakePage(),
        fields=[FieldDefinition(name="project_name", description="项目名称")],
        output_dir="output",
        xpath_registry=registry,
    )

    result = await worker.extract("https://example.com/detail/1")

    assert result.record.success is True
    assert result.record.get_field_value("project_name") == "测试项目"
    assert registry.records == [
        ("https://example.com/detail/1", False, '//*[@id="cached"]'),
        ("https://example.com/detail/1", True, '//*[@id="llm"]'),
    ]


@pytest.mark.asyncio
async def test_detail_page_worker_returns_xpath_result_without_llm(monkeypatch):
    registry = _RegistryStub(
        [
            {
                "name": "project_name",
                "description": "项目名称",
                "xpath": '//*[@id="cached"]',
                "xpath_fallbacks": [],
                "required": True,
                "data_type": "text",
            }
        ]
    )

    class _FakeBatchXPathExtractor:
        def __init__(self, *args, **kwargs):
            return None

        async def _extract_from_url(self, url: str):
            return PageExtractionRecord(
                url=url,
                fields=[
                    FieldExtractionResult(
                        field_name="project_name",
                        value="缓存命中",
                        xpath='//*[@id="cached"]',
                    )
                ],
                success=True,
            )

    class _FailingFieldExtractor:
        def __init__(self, *args, **kwargs):
            return None

        async def extract_from_url(self, url: str):
            raise AssertionError("llm extractor should not run")

    monkeypatch.setattr(worker_module, "BatchXPathExtractor", _FakeBatchXPathExtractor)
    monkeypatch.setattr(worker_module, "FieldExtractor", _FailingFieldExtractor)

    worker = worker_module.DetailPageWorker(
        page=_FakePage(),
        fields=[FieldDefinition(name="project_name", description="项目名称")],
        output_dir="output",
        xpath_registry=registry,
    )

    result = await worker.extract("https://example.com/detail/2")

    assert result.record.success is True
    assert result.record.get_field_value("project_name") == "缓存命中"
    assert registry.records == [("https://example.com/detail/2", True, '//*[@id="cached"]')]
