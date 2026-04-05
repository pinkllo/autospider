"""逐条详情页提取执行器。"""

from __future__ import annotations

from dataclasses import dataclass

from autospider.common.storage.field_xpath_registry import FieldXPathRegistry
from autospider.domain.fields import FieldDefinition

from .batch_xpath_extractor import BatchXPathExtractor
from .field_extractor import FieldExtractor
from .models import PageExtractionRecord


@dataclass(frozen=True, slots=True)
class DetailPageWorkerResult:
    record: PageExtractionRecord
    extraction_config: dict


class DetailPageWorker:
    """对单个详情页执行“先规则、后 LLM”的提取。"""

    def __init__(
        self,
        *,
        page,
        fields: list[FieldDefinition],
        output_dir: str,
        skill_runtime: object | None = None,
        xpath_registry: FieldXPathRegistry | None = None,
    ) -> None:
        self.page = page
        self.fields = list(fields or [])
        self.output_dir = output_dir
        self.skill_runtime = skill_runtime
        self.xpath_registry = xpath_registry or FieldXPathRegistry()

    async def extract(self, url: str) -> DetailPageWorkerResult:
        fields_config = self.xpath_registry.build_fields_config(url, self.fields)
        extraction_config = {"fields": fields_config}
        if self._has_rule_candidates(fields_config):
            xpath_record = await self._extract_with_xpath(url, fields_config)
            if xpath_record.success:
                self.xpath_registry.record(url, xpath_record, success=True)
                return DetailPageWorkerResult(record=xpath_record, extraction_config=extraction_config)
            self.xpath_registry.record(url, xpath_record, success=False)

        llm_record = await self._extract_with_llm(url)
        if any(field.value is not None for field in list(llm_record.fields or [])):
            self.xpath_registry.record(url, llm_record, success=True)
        return DetailPageWorkerResult(record=llm_record, extraction_config=extraction_config)

    def _has_rule_candidates(self, fields_config: list[dict]) -> bool:
        for field in fields_config:
            if str(field.get("xpath") or "").strip():
                return True
        return False

    async def _extract_with_xpath(self, url: str, fields_config: list[dict]) -> PageExtractionRecord:
        extractor = BatchXPathExtractor(
            page=self.page,
            fields_config=fields_config,
            output_dir=self.output_dir,
            skill_runtime=self.skill_runtime,
        )
        return await extractor._extract_from_url(url)

    async def _extract_with_llm(self, url: str) -> PageExtractionRecord:
        extractor = FieldExtractor(
            page=self.page,
            fields=self.fields,
            output_dir=self.output_dir,
            skill_runtime=self.skill_runtime,
        )
        return await extractor.extract_from_url(url)
