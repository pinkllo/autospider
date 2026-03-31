"""
基于公共 XPath 的批量字段提取器

该模块实现了一个高效的批量提取器，默认直接使用预先生成的公共 XPath 模式
在多个 URL 上执行抓取；当必填字段在页面中整体失效时，可原地触发 LLM 挽救流程，
若挽救后仍失败则自动升级到单页探索提取。
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
from ..common.experience import SkillRuntime
from ..common.llm import LLMDecider
from ..common.protocol import coerce_bool
from ..common.som import capture_screenshot_with_marks
from ..common.utils.fuzzy_search import FuzzyTextSearcher, TextMatch
from ..domain.fields import FieldDefinition
from .field_decider import FieldDecider
from .field_extractor import FieldExtractor

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
        skill_runtime: SkillRuntime | None = None,
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
        self.skill_runtime = skill_runtime or SkillRuntime()
        self.selected_skills_context = ""
        self.selected_skills: list[dict[str, str]] = []
        
        # 批量提取时页面经常异步渲染，增加统一的页面稳定等待
        # 该配置通过 config.url_collector.page_load_delay 获取
        self.page_load_delay = config.url_collector.page_load_delay
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 记录每个字段是否为必填，用于判断页面提取是否成功
        self.required_fields = {f.get("name"): f.get("required", True) for f in fields_config}
        self.fuzzy_searcher = FuzzyTextSearcher(
            threshold=config.url_collector.mark_id_match_threshold
        )

        # 批处理兜底：必填字段失败后可原地唤起 LLM 挽救
        self.batch_salvage_enabled = bool(config.field_extractor.batch_salvage_enabled)
        self.batch_salvage_max_fields = max(
            1, int(config.field_extractor.batch_salvage_max_fields_per_page)
        )
        self.batch_salvage_min_confidence = max(
            0.0, min(1.0, float(config.field_extractor.batch_salvage_min_confidence))
        )

        self.salvage_llm_decider: LLMDecider | None = None
        self.salvage_field_decider: FieldDecider | None = None
        if self.batch_salvage_enabled:
            try:
                self.salvage_llm_decider = LLMDecider(
                    api_key=config.llm.api_key,
                    api_base=config.llm.api_base,
                    model=config.llm.model,
                )
                self.salvage_field_decider = FieldDecider(
                    page=self.page,
                    decider=self.salvage_llm_decider,
                    selected_skills_context=self.selected_skills_context,
                    selected_skills=self.selected_skills,
                )
            except Exception as e:
                # 若模型不可用，自动降级为纯 XPath 模式，避免阻塞批处理
                self.batch_salvage_enabled = False
                logger.info(f"[BatchXPathExtractor] 挽救模式初始化失败，已自动降级: {e}")

        # 挽救失败后的升级兜底：自动切换到单页探索提取
        self.explore_upgrade_extractor: FieldExtractor | None = None

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
        await self._prepare_skill_context(url)

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
            xpath_chain = self._build_xpath_chain(field)
            xpath = xpath_chain[0] if xpath_chain else None
            result = FieldExtractionResult(
                field_name=name,
                xpath=xpath,
                extraction_method="xpath",
            )

            if not xpath_chain:
                fill_value, fill_method = self._resolve_non_xpath_field_value(field, url=url)
                if fill_method:
                    result.value = fill_value
                    result.confidence = 1.0
                    result.extraction_method = fill_method
                    record.fields.append(result)
                    continue
                result.error = "未提供 XPath"
                record.fields.append(result)
                continue

            last_error: str | None = None
            for idx, xpath_candidate in enumerate(xpath_chain):
                try:
                    # 检查页面状态并尝试提取
                    await self._ensure_page()
                    locator = self.page.locator(f"xpath={xpath_candidate}")
                    value, error = await self._extract_field_value(locator, field)
                    if value is not None:
                        result.value = value
                        result.xpath = xpath_candidate
                        result.confidence = 0.9
                        if idx > 0:
                            logger.info(
                                "[BatchXPathExtractor] 字段 '%s' 主 XPath 未命中，回退成功: %s",
                                name,
                                xpath_candidate,
                            )
                        break
                    last_error = error or "XPath 未返回内容"
                except Exception as e:
                    # 针对“页面已关闭”错误进行容错处理
                    if self._is_closed_error(e):
                        try:
                            logger.info(
                                "[BatchXPathExtractor] 页面关闭，尝试恢复并重新提取: %s",
                                name,
                            )
                            await self._recover_and_reload(url)
                            locator = self.page.locator(f"xpath={xpath_candidate}")
                            value, error = await self._extract_field_value(locator, field)
                            if value is not None:
                                result.value = value
                                result.xpath = xpath_candidate
                                result.confidence = 0.9
                                if idx > 0:
                                    logger.info(
                                        "[BatchXPathExtractor] 字段 '%s' 回退 XPath 重试成功: %s",
                                        name,
                                        xpath_candidate,
                                    )
                                break
                            last_error = error or "XPath 未返回内容"
                        except Exception as retry_error:
                            last_error = f"XPath 提取失败: {retry_error}"
                    else:
                        last_error = f"XPath 提取失败: {e}"

            if result.value is None:
                result.error = last_error or "所有 XPath 候选均未命中"

            record.fields.append(result)

        required_fields_ok = self._required_fields_ok(record)
        if not required_fields_ok:
            await self._salvage_required_fields(record)
            required_fields_ok = self._required_fields_ok(record)
        if not required_fields_ok:
            await self._upgrade_to_exploration(record, url=url)
            required_fields_ok = self._required_fields_ok(record)
        record.success = required_fields_ok

        return record

    async def _prepare_skill_context(self, url: str) -> None:
        """为当前详情页选择并加载 skill 正文。"""
        llm = self.salvage_llm_decider.llm if self.salvage_llm_decider else None
        selected = await self.skill_runtime.get_or_select(
            phase="field_extractor",
            url=url,
            task_context={"fields": list(self.fields_config)},
            llm=llm,
        )
        self.selected_skills = [
            {
                "name": skill.name,
                "description": skill.description,
                "path": skill.path,
                "domain": skill.domain,
            }
            for skill in selected
        ]
        self.selected_skills_context = self.skill_runtime.format_selected_skills_context(
            self.skill_runtime.load_selected_bodies(selected)
        )
        if self.salvage_field_decider:
            self.salvage_field_decider.selected_skills = list(self.selected_skills)
            self.salvage_field_decider.selected_skills_context = self.selected_skills_context

    def _required_fields_ok(self, record: PageExtractionRecord) -> bool:
        """判断当前页面是否已满足全部必填字段。"""
        return all(
            record.get_field_value(name) is not None
            for name, required in self.required_fields.items()
            if required
        )

    def _collect_missing_required_fields(
        self,
        record: PageExtractionRecord,
    ) -> list[tuple[dict, FieldExtractionResult]]:
        """收集当前页面缺失值的必填字段。"""
        missing: list[tuple[dict, FieldExtractionResult]] = []
        for field in self.fields_config:
            if not isinstance(field, dict):
                continue
            name = str(field.get("name") or "").strip()
            if not name:
                continue
            if not bool(field.get("required", True)):
                continue
            result = record.get_field(name)
            if result is None:
                continue
            if result.value is None:
                missing.append((field, result))
        return missing

    def _to_field_definition(self, field: dict) -> FieldDefinition:
        """将批处理字段配置转换为 FieldDecider 可消费的字段定义。"""
        return FieldDefinition(
            name=str(field.get("name") or "").strip(),
            description=str(field.get("description") or "").strip(),
            required=bool(field.get("required", True)),
            data_type=str(field.get("data_type") or "text").strip().lower() or "text",
            example=(str(field.get("example")) if field.get("example") is not None else None),
            extraction_source=(
                str(field.get("extraction_source")).strip()
                if field.get("extraction_source") is not None
                else None
            ),
            fixed_value=(
                str(field.get("fixed_value")).strip()
                if field.get("fixed_value") is not None
                else None
            ),
        )

    async def _salvage_required_fields(self, record: PageExtractionRecord) -> None:
        """必填字段兜底：XPath 失败后原地唤起 LLM 提取并尝试动态重定位 XPath。"""
        if not self.batch_salvage_enabled or not self.salvage_field_decider:
            return

        missing = self._collect_missing_required_fields(record)
        if not missing:
            return

        await self._ensure_page()
        # 页面对象在恢复后可能变化，保证 decider 始终绑定最新 page。
        self.salvage_field_decider.page = self.page

        try:
            html_content = await self.page.content()
        except Exception:
            html_content = ""

        logger.info(
            "[BatchXPathExtractor] 必填字段触发挽救: missing=%s",
            [str(field.get("name") or "") for field, _ in missing],
        )

        salvaged_count = 0
        for field, result in missing:
            if salvaged_count >= self.batch_salvage_max_fields:
                break
            ok = await self._salvage_single_required_field(
                field=field,
                result=result,
                html_content=html_content,
            )
            if ok:
                salvaged_count += 1

    async def _upgrade_to_exploration(self, record: PageExtractionRecord, url: str) -> None:
        """当 XPath + 挽救仍失败时，自动升级到单页探索提取。"""
        missing = self._collect_missing_required_fields(record)
        if not missing:
            return

        field_defs: list[FieldDefinition] = [self._to_field_definition(field) for field, _ in missing]
        if not field_defs:
            return

        logger.info(
            "[BatchXPathExtractor] 挽救后仍缺失必填字段，自动升级探索: missing=%s",
            [f.name for f in field_defs],
        )

        try:
            await self._ensure_page()
            if self.explore_upgrade_extractor is None:
                self.explore_upgrade_extractor = FieldExtractor(
                    page=self.page,
                    fields=field_defs,
                    output_dir=str(self.output_dir),
                    max_nav_steps=config.field_extractor.max_nav_steps,
                    skill_runtime=self.skill_runtime,
                )
            else:
                self.explore_upgrade_extractor.page = self.page
                self.explore_upgrade_extractor.fields = field_defs
                self.explore_upgrade_extractor.field_decider.page = self.page
                self.explore_upgrade_extractor.action_executor.page = self.page

            explore_record = await self.explore_upgrade_extractor.extract_from_url(url)
        except Exception as e:
            logger.info("[BatchXPathExtractor] 自动升级探索失败: %s", e)
            for _, result in missing:
                if result.error:
                    result.error = f"{result.error}; explore_upgrade_failed: {e}"[:500]
                else:
                    result.error = f"explore_upgrade_failed: {e}"[:500]
            return

        explore_result_map = {field.field_name: field for field in explore_record.fields}
        for field, result in missing:
            name = str(field.get("name") or "").strip()
            upgraded = explore_result_map.get(name)
            if not upgraded:
                continue
            if upgraded.value is not None:
                result.value = upgraded.value
                result.confidence = max(result.confidence, upgraded.confidence)
                if upgraded.xpath:
                    result.xpath = upgraded.xpath
                if upgraded.xpath_candidates:
                    result.xpath_candidates = list(upgraded.xpath_candidates)
                result.extraction_method = "explore_upgrade"
                result.error = None
                result.salvage_reason = "explore_upgrade_succeeded"
            else:
                upgrade_error = upgraded.error or "explore_upgrade_no_value"
                if result.error:
                    result.error = f"{result.error}; {upgrade_error}"[:500]
                else:
                    result.error = upgrade_error[:500]

    async def _salvage_single_required_field(
        self,
        field: dict,
        result: FieldExtractionResult,
        html_content: str,
    ) -> bool:
        """对单个必填字段执行挽救。"""
        if not self.salvage_field_decider:
            return False

        field_def = self._to_field_definition(field)
        value, confidence, reason, trace = await self._extract_value_by_agent(
            field=field_def,
            html_content=html_content,
        )
        result.salvage_trace = trace

        if not value:
            result.salvage_reason = reason
            if not result.error:
                result.error = f"salvage_failed: {reason}"
            logger.info(
                "[BatchXPathExtractor] 字段 '%s' 挽救失败: %s",
                field_def.name,
                reason,
            )
            return False

        relocated_xpath, xpath_candidates = self._relocate_xpath_from_value(
            html_content=html_content,
            field=field,
            value=value,
        )
        if relocated_xpath:
            result.xpath = relocated_xpath
            result.xpath_candidates = xpath_candidates
        result.value = value
        result.confidence = max(result.confidence, confidence)
        result.extraction_method = "agent_salvage"
        result.error = None
        result.salvaged = True
        result.salvage_reason = "salvage_succeeded"

        logger.info(
            "[BatchXPathExtractor] 字段 '%s' 挽救成功%s",
            field_def.name,
            f"，动态重定位 XPath: {relocated_xpath}" if relocated_xpath else "",
        )
        return True

    async def _extract_value_by_agent(
        self,
        field: FieldDefinition,
        html_content: str,
    ) -> tuple[str | None, float, str, dict]:
        """用 LLM 对当前页面进行字段补救提取。"""
        if not self.salvage_field_decider:
            return None, 0.0, "salvage_not_initialized", {}

        trace: dict = {"field_name": field.name, "page_text_hit": None}

        page_text_hit: bool | None = None
        if html_content:
            try:
                page_text_hit = await self.salvage_field_decider.check_field_in_page_text(
                    html_content, field
                )
            except Exception as e:
                trace["page_text_check_error"] = str(e)
        trace["page_text_hit"] = page_text_hit

        try:
            _, screenshot_base64 = await capture_screenshot_with_marks(self.page)
            extract_result = await self.salvage_field_decider.extract_field_text(
                screenshot_base64=screenshot_base64,
                field=field,
            )
        except Exception as e:
            trace["extract_error"] = str(e)
            return None, 0.0, "llm_extract_exception", trace

        if not extract_result or extract_result.get("action") != "extract":
            trace["raw_result"] = extract_result or {}
            return None, 0.0, "llm_no_extract_action", trace

        args = extract_result.get("args") if isinstance(extract_result.get("args"), dict) else {}
        found = coerce_bool(args.get("found"))
        if found is None:
            found = bool(args.get("field_value") or args.get("field_text"))
        if not found:
            trace["raw_result"] = args
            return None, 0.0, "llm_marked_not_found", trace

        value = str(args.get("field_value") or args.get("field_text") or "").strip()
        if not value:
            trace["raw_result"] = args
            return None, 0.0, "llm_empty_value", trace

        confidence = self._coerce_confidence(args.get("confidence"), default=0.7)
        trace["confidence"] = confidence

        if confidence < self.batch_salvage_min_confidence:
            return None, confidence, "llm_confidence_too_low", trace

        data_type = (field.data_type or "text").strip().lower()
        if not self._is_value_semantically_valid(value, data_type):
            return None, confidence, "llm_value_semantic_invalid", trace

        return value, confidence, "ok", trace

    def _coerce_confidence(self, value: object, default: float = 0.7) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            confidence = default
        return max(0.0, min(1.0, confidence))

    def _is_value_semantically_valid(self, value: str, data_type: str) -> bool:
        """按字段类型做轻量语义校验，避免挽救阶段写入明显错误值。"""
        text = (value or "").strip()
        if not text:
            return False

        if self._is_url_type(data_type):
            return self._looks_like_url(text)
        if data_type == "number":
            return self._looks_like_number(text)
        if data_type == "date":
            return self._looks_like_date(text)

        # text 类型放宽，仅限制超长噪声文本
        return len(text) <= 300

    def _relocate_xpath_from_value(
        self,
        html_content: str,
        field: dict,
        value: str,
    ) -> tuple[str | None, list[dict]]:
        """根据挽救得到的值反查 HTML，动态生成更贴近当前页面的 XPath。"""
        if not html_content or not value:
            return None, []

        data_type = str(field.get("data_type") or "text").strip().lower()
        matches: list[TextMatch]

        if self._is_url_type(data_type):
            matches = self.fuzzy_searcher.search_url_in_html(html_content, value)
        else:
            matches = self.fuzzy_searcher.search_strict_in_html(html_content, value)
            if not matches:
                threshold = max(0.72, self.fuzzy_searcher.threshold - 0.08)
                matches = self.fuzzy_searcher.search_in_html(
                    html_content,
                    value,
                    threshold=threshold,
                )

        if not matches:
            return None, []

        best_match = self._pick_best_text_match(matches, data_type=data_type)
        if best_match is None:
            return None, []
        return best_match.element_xpath, best_match.xpath_candidates or []

    def _pick_best_text_match(self, matches: list[TextMatch], data_type: str) -> TextMatch | None:
        if not matches:
            return None

        scored: list[tuple[float, TextMatch]] = []
        for match in matches[:10]:
            semantic_score = self._score_candidate(match.text, data_type)
            score = semantic_score + match.similarity
            scored.append((score, match))

        scored.sort(key=lambda item: item[0], reverse=True)
        return scored[0][1] if scored else None

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

    def _build_xpath_chain(self, field: dict) -> list[str]:
        """构建字段 XPath 优先级链：主 XPath 在前，fallback 在后。"""
        primary = str(field.get("xpath") or "").strip()
        if not primary:
            return []

        chain: list[str] = []
        if " | " in primary:
            # 兼容历史 union 配置：`a | b` -> `a -> b`
            parts = [part.strip() for part in primary.split(" | ") if part.strip()]
            chain.extend(parts)
        else:
            chain.append(primary)

        fallbacks_raw = field.get("xpath_fallbacks")
        if isinstance(fallbacks_raw, list):
            for xpath in fallbacks_raw:
                value = str(xpath or "").strip()
                if value and value not in chain:
                    chain.append(value)

        return [xpath for xpath in chain if xpath.startswith("/")]

    def _resolve_non_xpath_field_value(
        self,
        field: dict,
        *,
        url: str,
    ) -> tuple[str | None, str | None]:
        source = str(field.get("extraction_source") or "").strip().lower()
        fixed_value = field.get("fixed_value")

        if source in {"constant", "subtask_context"}:
            if fixed_value is None:
                return None, None
            value = str(fixed_value).strip()
            return (value if value else None), source

        if source == "task_url":
            return url, "task_url"

        data_type = str(field.get("data_type") or "").strip().lower()
        name = str(field.get("name") or "").strip().lower()
        if data_type == "url" and name in {"detail_url", "url", "source_url", "page_url"}:
            return url, "task_url"
        return None, None

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
                            "salvaged": f.salvaged,
                            "salvage_reason": f.salvage_reason,
                            "salvage_trace": f.salvage_trace,
                        }
                        for f in r.fields
                    ],
                }
                for r in records
            ],
            "total_urls": len(records),
            "success_count": success_count,
            "created_at": "",
        }

    def _save_results(self, result_data: dict, records: list[PageExtractionRecord]) -> None:
        """将提取结果保存至文件"""
        # 保存结构化的详细结果
        result_path = self.output_dir / "batch_extraction_result.json"
        persisted_result = write_json_idempotent(result_path, result_data)
        result_data = dict(persisted_result or result_data)
        logger.info(f"\n[BatchXPathExtractor] 结果已保存: {result_path}")

        # 保存平铺的数据集（便于直接分发使用）
        items_path = self.output_dir / "extracted_items.json"
        items = []
        for record in records:
            item = {"url": record.url}
            for field_result in record.fields:
                item[field_result.field_name] = field_result.value
            items.append(item)

        write_json_idempotent(items_path, items, volatile_keys=set())
        logger.info(f"[BatchXPathExtractor] 明细已保存: {items_path}")

    def _print_record_summary(self, record: PageExtractionRecord) -> None:
        """在控制台打印单词页面提取的精简摘要"""
        status = "✓ 成功" if record.success else "✗ 部分失败"
        logger.info(f"[BatchXPathExtractor] {status} - {record.url[:60]}...")
        for field_result in record.fields:
            if field_result.value:
                extra = " (salvaged)" if field_result.salvaged else ""
                logger.info(
                    f"    • {field_result.field_name}{extra}: {field_result.value[:40]}..."
                )
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
