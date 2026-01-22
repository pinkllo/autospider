"""基于公共 XPath 的批量字段提取器"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ..common.config import config

from .models import FieldExtractionResult, PageExtractionRecord

if TYPE_CHECKING:
    from playwright.async_api import Page


class BatchXPathExtractor:
    """批量字段提取器（使用公共 XPath）"""

    def __init__(
        self,
        page: "Page",
        fields_config: list[dict],
        output_dir: str = "output",
        timeout_ms: int = 5000,
    ):
        self.page = page
        self.fields_config = fields_config
        self.output_dir = Path(output_dir)
        self.timeout_ms = timeout_ms
        # 修改原因：批量提取时页面经常异步渲染，增加统一的页面稳定等待（可通过 env PAGE_LOAD_DELAY 调整）
        self.page_load_delay = config.url_collector.page_load_delay
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.required_fields = {f.get("name"): f.get("required", True) for f in fields_config}

    async def run(self, urls: list[str]) -> dict:
        """执行批量提取流程"""
        # 修改原因：URL 文件可能包含重复或空行，先去重以避免重复爬取。
        original_count = len(urls)
        unique_urls: list[str] = []
        seen: set[str] = set()
        for url in urls:
            if not url:
                continue
            cleaned = url.strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            unique_urls.append(cleaned)
        if len(unique_urls) != original_count:
            print(f"[BatchXPathExtractor] URL 去重: {original_count} -> {len(unique_urls)}")
        urls = unique_urls

        print(f"\n{'='*60}")
        print("[BatchXPathExtractor] 开始批量字段提取")
        print(f"[BatchXPathExtractor] 目标字段: {[f.get('name') for f in self.fields_config]}")
        print(f"[BatchXPathExtractor] URL 数量: {len(urls)}")
        print(f"{'='*60}\n")

        records: list[PageExtractionRecord] = []

        for i, url in enumerate(urls):
            print(f"\n[BatchXPathExtractor] 提取 {i + 1}/{len(urls)}: {url[:80]}...")
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
        except Exception as e:
            for field in self.fields_config:
                record.fields.append(
                    FieldExtractionResult(
                        field_name=field.get("name", ""),
                        xpath=field.get("xpath"),
                        extraction_method="xpath",
                        error=f"页面加载失败: {e}",
                    )
                )
            record.success = False
            return record

        for field in self.fields_config:
            name = field.get("name", "")
            xpath = field.get("xpath")
            result = FieldExtractionResult(
                field_name=name,
                xpath=xpath,
                extraction_method="xpath",
            )

            if not xpath:
                result.error = "未提供 XPath"
                record.fields.append(result)
                continue

            try:
                await self._ensure_page()
                element = self.page.locator(f"xpath={xpath}").first
                value = await element.inner_text(timeout=self.timeout_ms)
                value = value.strip()
                if value:
                    result.value = value
                    result.confidence = 0.9
                else:
                    result.error = "XPath 未返回内容"
            except Exception as e:
                if self._is_closed_error(e):
                    try:
                        await self._recover_and_reload(url)
                        element = self.page.locator(f"xpath={xpath}").first
                        value = await element.inner_text(timeout=self.timeout_ms)
                        value = value.strip()
                        if value:
                            result.value = value
                            result.confidence = 0.9
                        else:
                            result.error = "XPath 未返回内容"
                    except Exception as retry_error:
                        result.error = f"XPath 提取失败: {retry_error}"
                else:
                    result.error = f"XPath 提取失败: {e}"

            record.fields.append(result)

        required_fields_ok = all(
            record.get_field_value(name) is not None
            for name, required in self.required_fields.items()
            if required
        )
        record.success = required_fields_ok

        return record

    async def _safe_goto(self, url: str) -> None:
        await self._ensure_page()
        try:
            await self.page.goto(url, wait_until="domcontentloaded")
            await self._wait_for_stable()
        except Exception as e:
            if self._is_closed_error(e):
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
        # 修改原因：页面加载/异步渲染偏慢时，避免过快进入 XPath 提取导致超时。
        if self.page_load_delay > 0:
            await asyncio.sleep(self.page_load_delay)
        try:
            await self.page.wait_for_load_state("networkidle", timeout=self.timeout_ms)
        except Exception:
            # networkidle 可能因长连接不触发，超时直接继续
            pass

    async def _reopen_page(self) -> None:
        context = None
        try:
            context = self.page.context
        except Exception:
            context = None

        if context is not None:
            try:
                if hasattr(context, "is_closed") and context.is_closed():
                    context = None
            except Exception:
                context = None

        if context is None:
            raise RuntimeError("页面或上下文已关闭，无法恢复")

        self.page = await context.new_page()

    def _build_result_data(self, records: list[PageExtractionRecord]) -> dict:
        success_count = sum(1 for r in records if r.success)
        return {
            "fields": self.fields_config,
            "records": [
                {
                    "url": r.url,
                    "success": r.success,
                    "fields": [
                        {
                            "field_name": f.field_name,
                            "value": f.value,
                            "xpath": f.xpath,
                            "confidence": f.confidence,
                            "error": f.error,
                        }
                        for f in r.fields
                    ],
                }
                for r in records
            ],
            "total_urls": len(records),
            "success_count": success_count,
            "created_at": datetime.now().isoformat(),
        }

    def _save_results(self, result_data: dict, records: list[PageExtractionRecord]) -> None:
        result_path = self.output_dir / "batch_extraction_result.json"
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(result_data, f, ensure_ascii=False, indent=2)
        print(f"\n[BatchXPathExtractor] 结果已保存: {result_path}")

        items_path = self.output_dir / "extracted_items.json"
        items = []
        for record in records:
            item = {"url": record.url}
            for field_result in record.fields:
                item[field_result.field_name] = field_result.value
            items.append(item)

        with open(items_path, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        print(f"[BatchXPathExtractor] 明细已保存: {items_path}")

    def _print_record_summary(self, record: PageExtractionRecord) -> None:
        status = "✓ 成功" if record.success else "✗ 部分失败"
        print(f"[BatchXPathExtractor] {status} - {record.url[:60]}...")
        for field_result in record.fields:
            if field_result.value:
                print(f"    • {field_result.field_name}: {field_result.value[:40]}...")
            else:
                print(f"    • {field_result.field_name}: (未提取) {field_result.error or ''}")


async def batch_extract_fields_from_urls(
    page: "Page",
    urls: list[str],
    fields_config: list[dict],
    output_dir: str = "output",
    timeout_ms: int = 5000,
) -> dict:
    """便捷函数：从 URL 列表批量提取字段（基于 XPath）"""
    extractor = BatchXPathExtractor(
        page=page,
        fields_config=fields_config,
        output_dir=output_dir,
        timeout_ms=timeout_ms,
    )
    return await extractor.run(urls=urls)
