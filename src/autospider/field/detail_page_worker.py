"""逐条详情页提取执行器。"""

from __future__ import annotations

from dataclasses import dataclass

from autospider.common.logger import get_logger
from autospider.contexts.collection.infrastructure.repositories.field_xpath_repository import (
    FieldXPathQueryService,
    FieldXPathWriteService,
)
from autospider.domain.fields import FieldDefinition

from .batch_xpath_extractor import BatchXPathExtractor
from .field_extractor import FieldExtractor
from .field_config import ensure_extraction_config
from .models import ExtractionConfig, FieldRule, PageExtractionRecord

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
        decision_context: dict | None = None,
        world_snapshot: dict | None = None,
        failure_records: list[dict] | None = None,
        xpath_query_service: FieldXPathQueryService | None = None,
        xpath_write_service: FieldXPathWriteService | None = None,
    ) -> None:
        self.page = page
        self.fields = list(fields or [])
        self.output_dir = output_dir
        self.skill_runtime = skill_runtime
        self.decision_context = dict(decision_context or {})
        self.world_snapshot = dict(world_snapshot or {})
        self.failure_records = [dict(item) for item in list(failure_records or [])]
        self.xpath_query_service = xpath_query_service or FieldXPathQueryService()
        self.xpath_write_service = xpath_write_service or FieldXPathWriteService()

    async def extract(self, url: str) -> DetailPageWorkerResult:
        extraction_config = ensure_extraction_config(
            {"fields": self.xpath_query_service.build_fields_config(url, self.fields)}
        )
        mode = "xpath" if self._has_rule_candidates(extraction_config.fields) else "llm"
        logger.info("[DetailWorker] 开始处理: %s | mode=%s", url, mode)
        if self._has_rule_candidates(extraction_config.fields):
            xpath_record = await self._extract_with_xpath(url, extraction_config)
            if xpath_record.success:
                self.xpath_write_service.record(url, xpath_record, success=True)
                logger.info("[DetailWorker] 处理完成: %s | mode=xpath | success=%s", url, xpath_record.success)
                return DetailPageWorkerResult(
                    record=xpath_record,
                    extraction_config=extraction_config.to_payload(),
                )
            self.xpath_write_service.record(url, xpath_record, success=False)
            logger.info("[DetailWorker] XPath 未完成命中，回退 LLM: %s", url)

        llm_record = await self._extract_with_llm(url)
        if any(field.value is not None for field in list(llm_record.fields or [])):
            self.xpath_write_service.record(url, llm_record, success=True)
        logger.info("[DetailWorker] 处理完成: %s | mode=llm | success=%s", url, llm_record.success)
        return DetailPageWorkerResult(record=llm_record, extraction_config=extraction_config.to_payload())

    def _has_rule_candidates(self, field_rules: tuple[FieldRule, ...]) -> bool:
        return any(rule.has_rule_candidate() for rule in field_rules)

    async def _extract_with_xpath(
        self,
        url: str,
        extraction_config: ExtractionConfig,
    ) -> PageExtractionRecord:
        extractor = BatchXPathExtractor(
            page=self.page,
            fields_config=extraction_config.fields,
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
            decision_context=self.decision_context,
            world_snapshot=self.world_snapshot,
            failure_records=self.failure_records,
        )
        return await extractor.extract_from_url(url)
