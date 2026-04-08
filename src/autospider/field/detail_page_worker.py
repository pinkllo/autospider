"""逐条详情页提取执行器。"""

from __future__ import annotations

from dataclasses import dataclass

from autospider.common.logger import get_logger
from autospider.common.storage.field_xpath_query_service import FieldXPathQueryService
from autospider.common.storage.field_xpath_write_service import FieldXPathWriteService
from autospider.domain.fields import FieldDefinition

from .batch_xpath_extractor import BatchXPathExtractor
from .field_extractor import FieldExtractor
from .models import PageExtractionRecord

logger = get_logger(__name__)


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
        xpath_query_service: FieldXPathQueryService | None = None,
        xpath_write_service: FieldXPathWriteService | None = None,
    ) -> None:
        self.page = page
        self.fields = list(fields or [])
        self.output_dir = output_dir
        self.skill_runtime = skill_runtime
        self.xpath_query_service = xpath_query_service or FieldXPathQueryService()
        self.xpath_write_service = xpath_write_service or FieldXPathWriteService()

    async def extract(self, url: str) -> DetailPageWorkerResult:
        fields_config = self.xpath_query_service.build_fields_config(url, self.fields)
        extraction_config = {"fields": fields_config}
        mode = "xpath" if self._has_rule_candidates(fields_config) else "llm"
        logger.info("[DetailWorker] 开始处理: %s | mode=%s", url, mode)
        if self._has_rule_candidates(fields_config):
            xpath_record = await self._extract_with_xpath(url, fields_config)
            if xpath_record.success:
                self.xpath_write_service.record(url, xpath_record, success=True)
                logger.info("[DetailWorker] 处理完成: %s | mode=xpath | success=%s", url, xpath_record.success)
                return DetailPageWorkerResult(record=xpath_record, extraction_config=extraction_config)
            self.xpath_write_service.record(url, xpath_record, success=False)
            logger.info("[DetailWorker] XPath 未完成命中，回退 LLM: %s", url)

        llm_record = await self._extract_with_llm(url)
        if any(field.value is not None for field in list(llm_record.fields or [])):
            self.xpath_write_service.record(url, llm_record, success=True)
        logger.info("[DetailWorker] 处理完成: %s | mode=llm | success=%s", url, llm_record.success)
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
