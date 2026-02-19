"""
基于公共 XPath 的批量字段提取器

该模块实现了一个高效的批量提取器，它不依赖 LLM 进行实时决策，
而是直接使用预先生成的公共 XPath 模式在多个 URL 上执行抓取。
主要特点：
1. 性能高：直接使用 XPath 定位，无需视觉分析。
2. 健壮性：内置页面关闭恢复机制和安全加载逻辑。
3. 自动化：支持 URL 去重、结果汇总保存。
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from ..common.config import config

from .models import FieldExtractionResult, PageExtractionRecord

if TYPE_CHECKING:
    from playwright.async_api import Page
from autospider.common.logger import get_logger

logger = get_logger(__name__)


class BatchXPathExtractor:
    """批量字段提取器（使用公共 XPath）
    
    该类负责利用已知 XPath 模式，对大规模 URL 列表进行自动化字段抓取。
    """

    def __init__(
        self,
        page: "Page",
        fields_config: list[dict],
        output_dir: str = "output",
        timeout_ms: int = 5000,
    ):
        """
        初始化批量提取器

        Args:
            page: Playwright 页面对象
            fields_config: 字段配置列表，每个元素应包含 'name' 和 'xpath'
            output_dir: 结果输出目录
            timeout_ms: 单个 XPath 提取的超时时间（毫秒）
        """
        self.page = page
        self.fields_config = fields_config
        self.output_dir = Path(output_dir)
        self.timeout_ms = timeout_ms
        
        # 批量提取时页面经常异步渲染，增加统一的页面稳定等待
        # 该配置通过 config.url_collector.page_load_delay 获取
        self.page_load_delay = config.url_collector.page_load_delay
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 记录每个字段是否为必填，用于判断页面提取是否成功
        self.required_fields = {f.get("name"): f.get("required", True) for f in fields_config}

    async def run(self, urls: list[str]) -> dict:
        """
        执行完整批量提取流程

        Args:
            urls: 待抓取的 URL 列表

        Returns:
            汇总的提取结果字典
        """
        # URL 去重处理，避免重复爬取浪费系统资源
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
            logger.info(f"[BatchXPathExtractor] URL 去重: {original_count} -> {len(unique_urls)}")
        urls = unique_urls

        logger.info(f"\n{'='*60}")
        logger.info("[BatchXPathExtractor] 开始批量字段提取")
        logger.info(f"[BatchXPathExtractor] 目标字段: {[f.get('name') for f in self.fields_config]}")
        logger.info(f"[BatchXPathExtractor] URL 数量: {len(urls)}")
        logger.info(f"{'='*60}\n")

        records: list[PageExtractionRecord] = []

        # 遍历 URL 进行抓取
        for i, url in enumerate(urls):
            logger.info(f"\n[BatchXPathExtractor] 提取 {i + 1}/{len(urls)}: {url[:80]}...")
            record = await self._extract_from_url(url)
            records.append(record)
            # 实时打印单页提取结果摘要
            self._print_record_summary(record)

        # 构建最终汇总数据并保存
        result_data = self._build_result_data(records)
        self._save_results(result_data, records)

        return result_data

    async def _extract_from_url(self, url: str) -> PageExtractionRecord:
        """从单个 URL 提取定义的字段值"""
        record = PageExtractionRecord(url=url)

        try:
            # 导航至页面
            await self._safe_goto(url)
        except Exception as e:
            # 页面加载失败时，标记所有字段为失败
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

        # 依次提取配置中的每个字段
        for field in self.fields_config:
            name = field.get("name", "")
            xpath = field.get("xpath")
            result = FieldExtractionResult(
                field_name=name,
                xpath=xpath,
                extraction_method="xpath",
            )

            if not xpath:
                if self._should_fill_with_task_url(field):
                    result.value = url
                    result.confidence = 1.0
                    result.extraction_method = "task_url"
                    record.fields.append(result)
                    continue
                result.error = "未提供 XPath"
                record.fields.append(result)
                continue

            try:
                # 检查页面状态并尝试提取
                await self._ensure_page()
                locator = self.page.locator(f"xpath={xpath}")
                value, error = await self._extract_field_value(locator, field)
                if value is not None:
                    result.value = value
                    result.confidence = 0.9
                else:
                    result.error = error or "XPath 未返回内容"
            except Exception as e:
                # 针对“页面已关闭”错误进行容错处理
                if self._is_closed_error(e):
                    try:
                        logger.info(f"[BatchXPathExtractor] 页面关闭，尝试恢复并重新提取: {name}")
                        await self._recover_and_reload(url)
                        locator = self.page.locator(f"xpath={xpath}")
                        value, error = await self._extract_field_value(locator, field)
                        if value is not None:
                            result.value = value
                            result.confidence = 0.9
                        else:
                            result.error = error or "XPath 未返回内容"
                    except Exception as retry_error:
                        result.error = f"XPath 提取失败: {retry_error}"
                else:
                    result.error = f"XPath 提取失败: {e}"

            record.fields.append(result)

        # 检查是否所有必填字段都成功提取
        required_fields_ok = all(
            record.get_field_value(name) is not None
            for name, required in self.required_fields.items()
            if required
        )
        record.success = required_fields_ok

        return record

    async def _extract_field_value(self, locator, field: dict) -> tuple[str | None, str | None]:
        """按字段语义提取单个字段值，避免 XPath 过宽时误取 `.first`。"""
        try:
            count = await locator.count()
        except Exception as e:
            return None, f"XPath 计数失败: {e}"

        if count <= 0:
            return None, "XPath 未匹配到元素"

        data_type = str(field.get("data_type") or "text").lower()
        prefer_url = self._is_url_type(data_type)

        # 采样多个候选，避免 .first 误命中
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

        best = self._select_best_candidate(
            candidates=candidates,
            data_type=data_type,
        )
        if best is None:
            return None, "XPath 匹配到多个候选且语义冲突（疑似范围过宽）"
        return best, None

    async def _read_candidate_value(self, element_locator, prefer_url: bool) -> str | None:
        """读取单个候选值；URL 字段优先取 href/src。"""
        try:
            if prefer_url:
                for attr in ("href", "src", "data-href"):
                    attr_val = await element_locator.get_attribute(attr, timeout=self.timeout_ms)
                    if attr_val and attr_val.strip():
                        return attr_val.strip()

            text = await element_locator.inner_text(timeout=self.timeout_ms)
            text = (text or "").strip()
            if text:
                return text
        except Exception:
            return None
        return None

    def _select_best_candidate(
        self,
        candidates: list[str],
        data_type: str,
    ) -> str | None:
        """从多候选中按语义选优。"""
        unique_candidates: list[str] = []
        seen: set[str] = set()
        for value in candidates:
            if value in seen:
                continue
            seen.add(value)
            unique_candidates.append(value)

        scored = []
        for value in unique_candidates:
            score = self._score_candidate(
                value=value,
                data_type=data_type,
            )
            scored.append((score, value))

        scored.sort(key=lambda x: x[0], reverse=True)
        if not scored:
            return None

        top_score, top_value = scored[0]
        if top_score < 0:
            return None

        # Top2 分差过小且值不同，判定歧义，避免误提取
        if len(scored) > 1:
            second_score, second_value = scored[1]
            if (top_score - second_score) < 1.0 and self._normalize_text(top_value) != self._normalize_text(second_value):
                return None

        return top_value

    def _score_candidate(
        self,
        value: str,
        data_type: str,
    ) -> float:
        score = 0.0
        text = value.strip()
        if not text:
            return -10.0

        # 通用：文本过长通常是容器误命中
        if len(text) > 120:
            score -= 3.0
        elif len(text) <= 40:
            score += 0.5

        if self._is_url_type(data_type):
            if self._looks_like_url(text):
                score += 4.0
            else:
                score -= 4.0
            return score

        if data_type == "number":
            if self._looks_like_number(text):
                score += 3.0
            else:
                score -= 4.0
            return score

        if data_type == "date":
            if self._looks_like_date(text):
                score += 3.0
            else:
                score -= 3.0
            return score

        return score

    def _is_url_type(self, data_type: str) -> bool:
        return data_type == "url"

    def _should_fill_with_task_url(self, field: dict) -> bool:
        source = str(field.get("extraction_source") or "").strip().lower()
        if source == "task_url":
            return True

        data_type = str(field.get("data_type") or "").strip().lower()
        name = str(field.get("name") or "").strip().lower()
        if data_type == "url" and name in {"detail_url", "url", "source_url", "page_url"}:
            return True
        return False

    def _looks_like_url(self, value: str) -> bool:
        text = (value or "").strip()
        if text.startswith("/"):
            return True
        try:
            parsed = urlparse(text)
            return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
        except Exception:
            return False

    def _looks_like_number(self, value: str) -> bool:
        return bool(re.fullmatch(r"[^\d\-+]*[-+]?\d[\d,\.\s]*[^\d]*", (value or "").strip()))

    def _looks_like_date(self, value: str) -> bool:
        text = (value or "").strip()
        patterns = [
            r"\d{4}[-/年]\d{1,2}([-/月]\d{1,2}日?)?",
            r"\d{1,2}[-/]\d{1,2}([-/]\d{2,4})?",
        ]
        return any(re.search(p, text) for p in patterns)

    def _normalize_text(self, value: str) -> str:
        return re.sub(r"\s+", " ", value or "").strip().lower()

    async def _safe_goto(self, url: str) -> None:
        """安全地导航到指定 URL，包含简单的页面关闭恢复"""
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
        """确保页面对象处于打开且可用状态"""
        if self._is_page_closed():
            await self._reopen_page()

    def _is_page_closed(self) -> bool:
        """检查当前页面是否已关闭"""
        try:
            return self.page is None or self.page.is_closed()
        except Exception:
            return True

    def _is_closed_error(self, exc: Exception) -> bool:
        """判断异常是否属于 Playwright 的目标已关闭异常"""
        return "Target page, context or browser has been closed" in str(exc)

    async def _recover_and_reload(self, url: str) -> None:
        """当页面崩溃或关闭时，尝试重新打开并加载 URL"""
        await self._reopen_page()
        await self.page.goto(url, wait_until="domcontentloaded")
        await self._wait_for_stable()

    async def _wait_for_stable(self) -> None:
        """等待页面渲染稳定，避免异步内容未加载就提取"""
        # 如果配置了延迟，先进行强制等待
        if self.page_load_delay > 0:
            await asyncio.sleep(self.page_load_delay)
        try:
            # 尝试等待网络空闲
            await self.page.wait_for_load_state("networkidle", timeout=self.timeout_ms)
        except Exception:
            # networkidle 可能因长连接不触发，超时直接继续
            pass

    async def _reopen_page(self) -> None:
        """在原有上下文中重新开启一个新页面页签"""
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
        """根据所有页面记录构建最终的 JSON 结果对象"""
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
        """将提取结果保存至文件"""
        # 保存结构化的详细结果
        result_path = self.output_dir / "batch_extraction_result.json"
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(result_data, f, ensure_ascii=False, indent=2)
        logger.info(f"\n[BatchXPathExtractor] 结果已保存: {result_path}")

        # 保存平铺的数据集（便于直接分发使用）
        items_path = self.output_dir / "extracted_items.json"
        items = []
        for record in records:
            item = {"url": record.url}
            for field_result in record.fields:
                item[field_result.field_name] = field_result.value
            items.append(item)

        with open(items_path, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        logger.info(f"[BatchXPathExtractor] 明细已保存: {items_path}")

    def _print_record_summary(self, record: PageExtractionRecord) -> None:
        """在控制台打印单词页面提取的精简摘要"""
        status = "✓ 成功" if record.success else "✗ 部分失败"
        logger.info(f"[BatchXPathExtractor] {status} - {record.url[:60]}...")
        for field_result in record.fields:
            if field_result.value:
                logger.info(f"    • {field_result.field_name}: {field_result.value[:40]}...")
            else:
                logger.info(f"    • {field_result.field_name}: (未提取) {field_result.error or ''}")


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
