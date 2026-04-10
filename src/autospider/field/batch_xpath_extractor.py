"""基于公共 XPath 的批量字段提取器。"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from autospider.common.logger import get_logger

from ..common.config import config
from ..common.storage.idempotent_io import write_json_idempotent
from .field_config import (
    build_rule_xpath_chain,
    ensure_field_rules,
    resolve_field_rule_value,
)
from .models import ExtractionConfig, FieldExtractionResult, FieldRule, PageExtractionRecord
from .value_helpers import looks_like_date, looks_like_number, looks_like_url

if TYPE_CHECKING:
    from playwright.async_api import Page


logger = get_logger(__name__)


class BatchXPathExtractor:
    """纯规则批量提取器，只负责按既有 XPath 执行。"""

    def __init__(
        self,
        page: "Page",
        fields_config: Sequence[FieldRule | Mapping[str, object]],
        output_dir: str = "output",
        timeout_ms: int = 5000,
        skill_runtime: object | None = None,
    ):
        self.page = page
        self.field_rules = ensure_field_rules(fields_config)
        self.fields_config = ExtractionConfig(fields=tuple(self.field_rules)).to_payload()["fields"]
        self.output_dir = Path(output_dir)
        self.timeout_ms = timeout_ms
        self.skill_runtime = skill_runtime
        self.page_load_delay = config.url_collector.page_load_delay
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.required_fields = {
            rule.name: rule.required
            for rule in self.field_rules
            if rule.name
        }

    async def run(self, urls: list[str]) -> dict:
        unique_urls: list[str] = []
        seen: set[str] = set()
        for raw_url in urls:
            url = str(raw_url or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            unique_urls.append(url)

        logger.info(f"\n{'=' * 60}")
        logger.info("[BatchXPathExtractor] 开始规则批量提取")
        logger.info(f"[BatchXPathExtractor] 目标字段: {[rule.name for rule in self.field_rules]}")
        logger.info(f"[BatchXPathExtractor] URL 数量: {len(unique_urls)}")
        logger.info(f"{'=' * 60}\n")

        records: list[PageExtractionRecord] = []
        for index, url in enumerate(unique_urls, start=1):
            logger.info(f"\n[BatchXPathExtractor] 提取 {index}/{len(unique_urls)}: {url[:80]}...")
            record = await self._extract_from_url(url)
            records.append(record)
            self._print_record_summary(record)

        result_data = self._build_result_data(records)
        self._save_results(result_data, records)
        return result_data

    async def _extract_from_url(self, url: str) -> PageExtractionRecord:
        record = PageExtractionRecord(url=url)

        try:
            await self._safe_goto(url)
        except Exception as exc:  # noqa: BLE001
            for rule in self.field_rules:
                record.fields.append(
                    FieldExtractionResult(
                        field_name=rule.name,
                        xpath=rule.xpath,
                        extraction_method="xpath",
                        error=f"页面加载失败: {exc}",
                    )
                )
            record.success = False
            return record

        for rule in self.field_rules:
            name = rule.name
            xpath_chain = self._build_xpath_chain(rule)
            primary_xpath = xpath_chain[0] if xpath_chain else None
            result = FieldExtractionResult(
                field_name=name,
                xpath=primary_xpath,
                extraction_method="xpath",
            )

            if not xpath_chain:
                fill_value, fill_method = self._resolve_non_xpath_field_value(rule, url=url)
                if fill_method:
                    result.value = fill_value
                    result.confidence = 1.0
                    result.extraction_method = fill_method
                else:
                    result.error = "未提供 XPath"
                record.fields.append(result)
                continue

            last_error: str | None = None
            for idx, xpath_candidate in enumerate(xpath_chain):
                try:
                    await self._ensure_page()
                    locator = self.page.locator(f"xpath={xpath_candidate}")
                    value, error = await self._extract_field_value(locator, rule)
                except Exception as exc:  # noqa: BLE001
                    if self._is_closed_error(exc):
                        await self._recover_and_reload(url)
                        locator = self.page.locator(f"xpath={xpath_candidate}")
                        value, error = await self._extract_field_value(locator, rule)
                    else:
                        value, error = None, f"XPath 提取失败: {exc}"

                if value is not None:
                    result.value = value
                    result.xpath = xpath_candidate
                    result.confidence = 0.9
                    if idx > 0:
                        logger.info(
                            "[BatchXPathExtractor] 字段 '%s' 回退 XPath 命中: %s",
                            name,
                            xpath_candidate,
                        )
                    break
                last_error = error or "XPath 未返回内容"

            if result.value is None:
                result.error = last_error or "所有 XPath 候选均未命中"

            record.fields.append(result)

        record.success = self._required_fields_ok(record)
        return record

    def _required_fields_ok(self, record: PageExtractionRecord) -> bool:
        return all(
            record.get_field_value(name) is not None
            for name, required in self.required_fields.items()
            if required
        )

    async def _extract_field_value(
        self,
        locator,
        rule: FieldRule,
    ) -> tuple[str | None, str | None]:
        try:
            count = await locator.count()
        except Exception as exc:  # noqa: BLE001
            return None, f"XPath 计数失败: {exc}"

        if count <= 0:
            return None, "XPath 未匹配到元素"

        data_type = str(rule.data_type or "text").lower()
        prefer_url = self._is_url_type(data_type)
        max_candidates = min(count, 8)

        candidates: list[str] = []
        for idx in range(max_candidates):
            value = await self._read_candidate_value(locator.nth(idx), prefer_url=prefer_url)
            if value:
                cleaned = value.strip()
                if cleaned:
                    candidates.append(cleaned)

        if not candidates:
            return None, "XPath 未返回内容"

        best = self._select_best_candidate(candidates=candidates, data_type=data_type)
        if best is None:
            return None, "XPath 匹配到多个候选且语义冲突"
        return best, None

    async def _read_candidate_value(self, element_locator, prefer_url: bool) -> str | None:
        try:
            if prefer_url:
                for attr in ("href", "src", "data-href"):
                    value = await element_locator.get_attribute(attr, timeout=self.timeout_ms)
                    if value and value.strip():
                        return value.strip()

            text = await element_locator.inner_text(timeout=self.timeout_ms)
            text = (text or "").strip()
            if text:
                return text
        except Exception:
            return None
        return None

    def _select_best_candidate(self, candidates: list[str], data_type: str) -> str | None:
        unique_candidates: list[str] = []
        seen: set[str] = set()
        for value in candidates:
            if value in seen:
                continue
            seen.add(value)
            unique_candidates.append(value)

        scored = [(self._score_candidate(value, data_type), value) for value in unique_candidates]
        scored.sort(key=lambda item: item[0], reverse=True)
        if not scored:
            return None

        top_score, top_value = scored[0]
        if top_score < 0:
            return None

        if len(scored) > 1:
            second_score, second_value = scored[1]
            if (top_score - second_score) < 1.0 and self._normalize_text(top_value) != self._normalize_text(second_value):
                return None

        return top_value

    def _score_candidate(self, value: str, data_type: str) -> float:
        score = 0.0
        text = value.strip()
        if not text:
            return -10.0

        if len(text) > 120:
            score -= 3.0
        elif len(text) <= 40:
            score += 0.5

        if self._is_url_type(data_type):
            return score + 4.0 if looks_like_url(text) else score - 4.0
        if data_type == "number":
            return score + 3.0 if looks_like_number(text) else score - 4.0
        if data_type == "date":
            return score + 3.0 if looks_like_date(text) else score - 3.0
        return score

    def _normalize_text(self, value: str) -> str:
        return " ".join((value or "").strip().lower().split())

    def _is_url_type(self, data_type: str) -> bool:
        return data_type == "url"

    def _build_xpath_chain(self, rule: FieldRule) -> list[str]:
        return build_rule_xpath_chain(rule)

    def _resolve_non_xpath_field_value(
        self,
        rule: FieldRule,
        *,
        url: str,
    ) -> tuple[str | None, str | None]:
        return resolve_field_rule_value(rule, url=url)

    async def _safe_goto(self, url: str) -> None:
        await self._ensure_page()
        try:
            await self.page.goto(url, wait_until="domcontentloaded")
            await self._wait_for_stable()
        except Exception as exc:  # noqa: BLE001
            if self._is_closed_error(exc):
                await self._recover_and_reload(url)
            else:
                raise

    async def _ensure_page(self) -> None:
        if self._is_page_closed():
            await self._reopen_page()

    def _is_page_closed(self) -> bool:
        try:
            return self.page is None or self.page.is_closed()
        except Exception:
            return True

    def _is_closed_error(self, exc: Exception) -> bool:
        return "Target page, context or browser has been closed" in str(exc)

    async def _recover_and_reload(self, url: str) -> None:
        await self._reopen_page()
        await self.page.goto(url, wait_until="domcontentloaded")
        await self._wait_for_stable()

    async def _wait_for_stable(self) -> None:
        if self.page_load_delay > 0:
            await asyncio.sleep(self.page_load_delay)
        try:
            await self.page.wait_for_load_state("networkidle", timeout=self.timeout_ms)
        except Exception:
            pass

    async def _reopen_page(self) -> None:
        try:
            context = self.page.context
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("页面或上下文已关闭，无法恢复") from exc

        if hasattr(context, "is_closed") and context.is_closed():
            raise RuntimeError("页面上下文已关闭，无法恢复")
        self.page = await context.new_page()

    def _build_result_data(self, records: list[PageExtractionRecord]) -> dict:
        success_count = sum(1 for record in records if record.success)
        return {
            "fields": self.fields_config,
            "records": [
                {
                    "url": record.url,
                    "success": record.success,
                    "fields": [
                        {
                            "field_name": field.field_name,
                            "value": field.value,
                            "xpath": field.xpath,
                            "confidence": field.confidence,
                            "error": field.error,
                            "salvaged": field.salvaged,
                            "salvage_reason": field.salvage_reason,
                            "salvage_trace": field.salvage_trace,
                        }
                        for field in record.fields
                    ],
                }
                for record in records
            ],
            "total_urls": len(records),
            "success_count": success_count,
            "created_at": "",
        }

    def _save_results(self, result_data: dict, records: list[PageExtractionRecord]) -> None:
        result_path = self.output_dir / "batch_extraction_result.json"
        write_json_idempotent(result_path, result_data)
        logger.info(f"\n[BatchXPathExtractor] 结果已保存: {result_path}")

        items_path = self.output_dir / "extracted_items.json"
        items = []
        for record in records:
            item = {"url": record.url}
            for field in record.fields:
                item[field.field_name] = field.value
            items.append(item)

        write_json_idempotent(items_path, items, volatile_keys=set())
        logger.info(f"[BatchXPathExtractor] 明细已保存: {items_path}")

    def _print_record_summary(self, record: PageExtractionRecord) -> None:
        status = "✓ 成功" if record.success else "✗ 部分失败"
        logger.info(f"[BatchXPathExtractor] {status} - {record.url[:60]}...")
        for field in record.fields:
            if field.value:
                logger.info(f"    • {field.field_name}: {field.value[:40]}...")
            else:
                logger.info(f"    • {field.field_name}: (未提取) {field.error or ''}")


async def batch_extract_fields_from_urls(
    page: "Page",
    urls: list[str],
    fields_config: Sequence[FieldRule | Mapping[str, object]],
    output_dir: str = "output",
    timeout_ms: int = 5000,
) -> dict:
    extractor = BatchXPathExtractor(
        page=page,
        fields_config=fields_config,
        output_dir=output_dir,
        timeout_ms=timeout_ms,
    )
    return await extractor.run(urls=urls)
