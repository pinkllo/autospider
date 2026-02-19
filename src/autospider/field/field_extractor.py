"""核心字段提取器

实现从详情页提取目标字段的完整流程：
1. 导航阶段：使用 SoM + LLM 定位目标字段
2. 提取阶段：LLM 识别 → HTML 模糊搜索 → 消歧
3. XPath 提取和验证
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import TYPE_CHECKING

from ..common.som import (
    inject_and_scan,
    capture_screenshot_with_marks,
    clear_overlay,
    build_mark_id_to_xpath_map,
)
from ..common.som.text_first import resolve_single_mark_id
from ..common.browser import ActionExecutor
from ..common.types import Action, ActionType
from ..common.config import config
from ..common.logger import get_logger
from ..common.protocol import coerce_bool
from ..common.utils.fuzzy_search import FuzzyTextSearcher, TextMatch
from ..common.llm import LLMDecider

from .models import (
    FieldDefinition,
    FieldExtractionResult,
    PageExtractionRecord,
)

logger = get_logger(__name__)
from .field_decider import FieldDecider

if TYPE_CHECKING:
    from playwright.async_api import Page


def _escape_markup(text: str) -> str:
    return (text or "").replace("[", "[[").replace("]", "]]")


class FieldExtractor:
    """详情页字段提取器

    从单个详情页提取目标字段。
    """

    def __init__(
        self,
        page: "Page",
        fields: list[FieldDefinition],
        output_dir: str = "output",
        max_nav_steps: int = 10,
    ):
        """
        初始化字段提取器

        Args:
            page: Playwright 页面对象
            fields: 要提取的字段定义列表
            output_dir: 输出目录
            max_nav_steps: 单个字段最大导航步数
        """
        self.page = page
        self.fields = fields
        self.output_dir = Path(output_dir)
        self.max_nav_steps = max_nav_steps

        # 确保输出目录存在
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.screenshots_dir = self.output_dir / "screenshots"
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

        # 初始化组件
        self._initialize_components()

    def _initialize_components(self):
        """初始化各个组件"""
        # LLM 决策器
        self.llm_decider = LLMDecider(
            api_key=config.llm.api_key,
            api_base=config.llm.api_base,
            model=config.llm.model,
        )

        # 字段决策器
        self.field_decider = FieldDecider(
            page=self.page,
            decider=self.llm_decider,
        )

        # 动作执行器
        self.action_executor = ActionExecutor(self.page)

        # 模糊搜索器
        self.fuzzy_searcher = FuzzyTextSearcher(
            threshold=config.url_collector.mark_id_match_threshold
        )

    def _format_nav_steps_summary(
        self,
        nav_steps: list[dict],
        field_name: str,
        max_steps: int = 5,
    ) -> str:
        """格式化最近导航步骤摘要供 LLM 参考"""
        steps = [s for s in nav_steps if s.get("field_name") == field_name]
        if not steps:
            return "无"

        summary_lines = []
        for step in steps[-max_steps:]:
            action = step.get("action", "unknown")
            parts = [f"{step.get('step', '?')}. {action}"]
            decision = step.get("decision") or {}
            args = decision.get("args") if isinstance(decision.get("args"), dict) else {}
            mark_id = args.get("mark_id")
            if mark_id:
                parts.append(f"mark_id={mark_id}")
            summary_lines.append(" ".join(parts))

        return "\n".join(summary_lines)

    def _get_clicked_mark_ids(self, nav_steps: list[dict], field_name: str) -> set[int]:
        clicked: set[int] = set()
        for step in nav_steps:
            if step.get("field_name") != field_name:
                continue
            if step.get("action") != "click":
                continue
            decision = step.get("decision") or {}
            args = decision.get("args") if isinstance(decision.get("args"), dict) else {}
            mark_id = args.get("mark_id")
            try:
                clicked.add(int(mark_id))
            except (TypeError, ValueError):
                continue
        return clicked

    async def _get_full_page_html(self) -> str:
        try:
            return await self.page.content()
        except Exception as e:
            logger.info(f"[FieldExtractor] 获取页面 HTML 失败: {e}")
            return await self.page.inner_text("body")

    async def extract_from_url(self, url: str) -> PageExtractionRecord:
        """
        从单个 URL 提取所有字段

        Args:
            url: 详情页 URL

        Returns:
            页面提取记录
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"[FieldExtractor] 开始提取: {url}")
        logger.info(f"[FieldExtractor] 目标字段: {[f.name for f in self.fields]}")
        logger.info(f"{'='*60}\n")

        record = PageExtractionRecord(url=url)

        try:
            # 导航到页面
            await self.page.goto(url, wait_until="domcontentloaded")
            await asyncio.sleep(1.5)  # 等待页面加载

            # 提取每个字段
            for field in self.fields:
                logger.info(f"\n[FieldExtractor] --- 提取字段: {field.name} ---")
                result = await self._extract_single_field(field, record.nav_steps)
                record.fields.append(result)

                if result.value:
                    logger.info(
                        f"[FieldExtractor] ✓ 字段 '{field.name}' 提取成功: {result.value[:50]}..."
                    )
                else:
                    logger.info(f"[FieldExtractor] ✗ 字段 '{field.name}' 提取失败: {result.error}")

            # 检查是否所有必填字段都提取成功
            required_fields_ok = all(
                record.get_field_value(f.name) is not None for f in self.fields if f.required
            )
            record.success = required_fields_ok

        except Exception as e:
            logger.info(f"[FieldExtractor] 提取异常: {e}")
            import traceback

            traceback.print_exc()

        return record

    async def _extract_single_field(
        self,
        field: FieldDefinition,
        nav_steps: list[dict],
    ) -> FieldExtractionResult:
        """
        提取单个字段

        Args:
            field: 字段定义
            nav_steps: 导航步骤记录（会被修改）

        Returns:
            字段提取结果
        """
        result = FieldExtractionResult(field_name=field.name)

        html_content = await self._get_full_page_html()
        might_contain = await self.field_decider.check_field_in_page_text(html_content, field)

        if might_contain:
            _, screenshot_base64 = await capture_screenshot_with_marks(self.page)
            extract_result = await self.field_decider.extract_field_text(
                screenshot_base64=screenshot_base64,
                field=field,
            )
            if extract_result and extract_result.get("action") == "extract":
                args = (
                    extract_result.get("args")
                    if isinstance(extract_result.get("args"), dict)
                    else {}
                )
                found = coerce_bool(args.get("found"))
                if found is None:
                    found = bool(args.get("field_value") or args.get("field_text"))
                if found:
                    field_text = args.get("field_value") or args.get("field_text")
                    result.confidence = args.get("confidence", 0.8)
                    await self._finalize_extraction(result, field, field_text)
                    return result

        # 阶段 1：导航到目标字段
        nav_result = await self._navigate_to_field(field, nav_steps)

        if nav_result is None:
            result.error = "导航阶段未找到字段"
            return result

        nav_action = nav_result.get("action")
        nav_args = nav_result.get("args") if isinstance(nav_result.get("args"), dict) else {}

        if nav_action == "extract":
            found = coerce_bool(nav_args.get("found"))
            if found is None:
                found = bool(nav_args.get("field_value") or nav_args.get("field_text"))
            if not found:
                result.error = f"字段不存在: {nav_args.get('reasoning', '')}"
                return result

        # 阶段 2：提取字段值
        field_text = None
        if nav_action == "extract":
            field_text = nav_args.get("field_text") or nav_args.get("field_value")

        if not field_text:
            # 如果导航阶段没有直接返回文本，再次调用 LLM 提取
            _, screenshot_base64 = await capture_screenshot_with_marks(self.page)
            extract_result = await self.field_decider.extract_field_text(
                screenshot_base64=screenshot_base64,
                field=field,
            )

            if extract_result and extract_result.get("action") == "extract":
                args = (
                    extract_result.get("args")
                    if isinstance(extract_result.get("args"), dict)
                    else {}
                )
                found = coerce_bool(args.get("found"))
                if found is None:
                    found = bool(args.get("field_value") or args.get("field_text"))
                if found:
                    field_text = args.get("field_value") or args.get("field_text")
                    result.confidence = args.get("confidence", 0.8)

        if not field_text:
            result.error = "无法提取字段文本"
            return result

        await self._finalize_extraction(result, field, field_text)
        return result

    async def _finalize_extraction(
        self,
        result: FieldExtractionResult,
        field: FieldDefinition,
        field_text: str | None,
    ) -> None:
        if not field_text:
            result.error = "无法提取字段文本"
            return

        result.value = field_text
        result.extraction_method = "llm"

        xpath_result = await self._extract_xpath_for_text(field, field_text)
        if xpath_result:
            result.xpath = xpath_result.get("xpath")
            result.xpath_candidates = xpath_result.get("xpath_candidates", [])

            candidate_xpaths = []
            if result.xpath:
                candidate_xpaths.append(result.xpath)
            for candidate in result.xpath_candidates:
                if not isinstance(candidate, dict):
                    continue
                xpath = candidate.get("xpath")
                if isinstance(xpath, str) and xpath.strip():
                    candidate_xpaths.append(xpath.strip())

            best_xpath = await self._select_best_verified_xpath(
                candidates=candidate_xpaths,
                field=field,
                expected_value=field_text,
            )
            if best_xpath:
                if result.xpath and best_xpath != result.xpath:
                    logger.info(
                        f"[FieldExtractor] XPath 候选重选: {_escape_markup(result.xpath)} -> {_escape_markup(best_xpath)}"
                    )
                result.xpath = best_xpath
                result.confidence = max(result.confidence, 0.9)
                logger.info(f"[FieldExtractor] XPath 验证通过: {_escape_markup(result.xpath)}")
            else:
                logger.info("[FieldExtractor] XPath 验证失败，使用 LLM 提取的值")
                result.xpath = None

    async def _navigate_to_field(
        self,
        field: FieldDefinition,
        nav_steps: list[dict],
    ) -> dict | None:
        """
        导航到目标字段

        使用 SoM + LLM 两步策略，循环执行直到：
        - 找到目标字段
        - 达到最大步数
        - LLM 判断字段不存在

        Args:
            field: 字段定义
            nav_steps: 导航步骤记录

        Returns:
            最终决策结果
        """
        for step in range(self.max_nav_steps):
            logger.info(f"[FieldExtractor] 导航步骤 {step + 1}/{self.max_nav_steps}")

            # 获取 SoM 快照
            snapshot = await inject_and_scan(self.page)
            _, screenshot_base64 = await capture_screenshot_with_marks(self.page)

            html_content = await self._get_full_page_html()
            might_contain = await self.field_decider.check_field_in_page_text(html_content, field)

            # 让 LLM 决策
            nav_steps_summary = self._format_nav_steps_summary(nav_steps, field.name)
            decision = await self.field_decider.decide_navigation(
                snapshot=snapshot,
                screenshot_base64=screenshot_base64,
                field=field,
                nav_steps_count=step,
                nav_steps_summary=nav_steps_summary,
                scroll_info=snapshot.scroll_info,
                page_text_hit=might_contain,
            )

            if not decision:
                logger.info("[FieldExtractor] LLM 决策失败，继续尝试")
                continue

            action = decision.get("action")
            args = decision.get("args") if isinstance(decision.get("args"), dict) else {}

            if action == "scroll" and not might_contain:
                clicked_ids = self._get_clicked_mark_ids(nav_steps, field.name)
                candidates = self.field_decider.get_clickable_candidate_ids(
                    snapshot, exclude_ids=clicked_ids, max_candidates=5
                )
                if candidates:
                    action = "click"
                    decision["action"] = "click"
                    if not isinstance(decision.get("args"), dict):
                        decision["args"] = {}
                    decision["args"]["mark_id"] = candidates[0]
                    args = decision["args"]

            # 记录导航步骤
            nav_steps.append(
                {
                    "step": step + 1,
                    "action": action,
                    "field_name": field.name,
                    "decision": decision,
                    "url": self.page.url,
                }
            )

            # 处理不同的决策
            if action == "extract":
                found = coerce_bool(args.get("found"))
                if found is None:
                    found = bool(args.get("field_value") or args.get("field_text"))
                if found:
                    field_text = args.get("field_value") or args.get("field_text") or ""
                    logger.info(f"[FieldExtractor] ✓ 找到字段: {field_text[:50]}...")
                    await clear_overlay(self.page)
                    return decision
                logger.info("[FieldExtractor] ✗ 字段不存在")
                await clear_overlay(self.page)
                return decision

            elif action == "click":
                mark_id_raw = args.get("mark_id")
                target_text = args.get("target_text") or ""
                mark_id_value = None
                if mark_id_raw is not None:
                    try:
                        mark_id_value = int(mark_id_raw)
                    except (TypeError, ValueError):
                        mark_id_value = None

                # 修改原因：字段导航点击同样经常出现“文本选对但 mark_id 读错/歧义”的问题，统一用文本优先纠正
                if config.url_collector.validate_mark_id and target_text:
                    mark_id_value = await resolve_single_mark_id(
                        page=self.page,
                        llm=self.llm_decider.llm,
                        snapshot=snapshot,
                        mark_id=mark_id_value,
                        target_text=target_text,
                        max_retries=config.url_collector.max_validation_retries,
                    )

                if mark_id_value is not None:
                    await self._execute_click(mark_id_value, snapshot)
                await asyncio.sleep(1.0)

            elif action == "type":
                mark_id = args.get("mark_id")
                target_text = args.get("target_text") or ""
                text = args.get("text")
                if mark_id and text:
                    try:
                        mark_id_value = int(mark_id)
                        if config.url_collector.validate_mark_id and target_text:
                            mark_id_value = await resolve_single_mark_id(
                                page=self.page,
                                llm=self.llm_decider.llm,
                                snapshot=snapshot,
                                mark_id=mark_id_value,
                                target_text=target_text,
                                max_retries=config.url_collector.max_validation_retries,
                            )
                        await self._execute_type(mark_id_value, text, snapshot)
                    except (TypeError, ValueError):
                        logger.info(f"[FieldExtractor] 输入动作 mark_id 无效: {mark_id}")
                else:
                    logger.info("[FieldExtractor] 输入动作缺少 mark_id 或 text")
                await asyncio.sleep(0.5)

            elif action == "scroll":
                delta = args.get("scroll_delta")
                if isinstance(delta, (list, tuple)) and len(delta) == 2:
                    dx, dy = int(delta[0]), int(delta[1])
                else:
                    dx, dy = 0, 500
                await self.page.evaluate("([dx, dy]) => window.scrollBy(dx, dy)", [dx, dy])
                await asyncio.sleep(0.5)

            else:
                logger.info(f"[FieldExtractor] 未知操作: {action}")

            # 清除 SoM 覆盖层
            await clear_overlay(self.page)

        logger.info(f"[FieldExtractor] 达到最大导航步数 {self.max_nav_steps}")
        return None

    async def _execute_click(self, mark_id: int, snapshot) -> bool:
        """执行点击操作"""
        try:
            mark_id_to_xpath = build_mark_id_to_xpath_map(snapshot)

            action = Action(
                action=ActionType.CLICK,
                mark_id=mark_id,
            )

            result, _ = await self.action_executor.execute(
                action=action,
                mark_id_to_xpath=mark_id_to_xpath,
                step_index=0,
            )

            return result.success
        except Exception as e:
            logger.info(f"[FieldExtractor] 点击失败: {e}")
            return False

    async def _execute_type(self, mark_id: int, text: str, snapshot) -> bool:
        """执行输入操作"""
        try:
            mark_id_to_xpath = build_mark_id_to_xpath_map(snapshot)

            action = Action(
                action=ActionType.TYPE,
                mark_id=mark_id,
                text=text,
            )

            result, _ = await self.action_executor.execute(
                action=action,
                mark_id_to_xpath=mark_id_to_xpath,
                step_index=0,
            )

            return result.success
        except Exception as e:
            logger.info(f"[FieldExtractor] 输入失败: {e}")
            return False

    async def _extract_xpath_for_text(
        self,
        field: FieldDefinition,
        target_text: str,
    ) -> dict | None:
        """
        在 HTML 中搜索目标文本并提取 XPath

        Args:
            field: 字段定义
            target_text: 目标文本

        Returns:
            XPath 提取结果
        """
        logger.info(f"[FieldExtractor] 在 HTML 中搜索: '{target_text[:30]}...'")

        # 获取页面 HTML
        html_content = await self.page.content()

        # URL 字段优先按 href/src 等属性匹配，避免把脚本中的链接误定位到价格等可视文本节点
        if (field.data_type or "").lower() == "url":
            url_matches = self.fuzzy_searcher.search_url_in_html(html_content, target_text)
            if url_matches:
                logger.info(f"[FieldExtractor] URL 属性匹配: 找到 {len(url_matches)} 个候选")
                selected_match = self._select_best_url_match(url_matches, target_text)
                if selected_match:
                    all_candidates = self._merge_xpath_candidates(url_matches, selected_match)
                    return {
                        "xpath": selected_match.element_xpath,
                        "xpath_candidates": all_candidates,
                        "match": selected_match,
                    }

        # 模糊搜索
        matches = self.fuzzy_searcher.search_in_html(html_content, target_text)

        if not matches:
            logger.info("[FieldExtractor] HTML 中未找到匹配")
            return None

        logger.info(f"[FieldExtractor] 找到 {len(matches)} 个匹配")

        if len(matches) == 1:
            # 唯一匹配，直接使用
            match = matches[0]
            logger.info(
                f"[FieldExtractor] 唯一匹配: xpath={_escape_markup(match.element_xpath)}"
            )
            all_candidates = self._merge_xpath_candidates([match], match)
            return {
                "xpath": match.element_xpath,
                "xpath_candidates": all_candidates,
                "match": match,
            }

        # 多个匹配，需要消歧
        logger.info("[FieldExtractor] 多个匹配，启动消歧流程")
        selected_match = await self._disambiguate_matches(field, matches)

        if selected_match:
            all_candidates = self._merge_xpath_candidates(matches, selected_match)
            return {
                "xpath": selected_match.element_xpath,
                "xpath_candidates": all_candidates,
                "match": selected_match,
            }

        # 消歧失败，使用第一个匹配
        all_candidates = self._merge_xpath_candidates(matches, matches[0])
        return {
            "xpath": matches[0].element_xpath,
            "xpath_candidates": all_candidates,
        }

    async def _disambiguate_matches(
        self,
        field: FieldDefinition,
        matches: list[TextMatch],
    ) -> TextMatch | None:
        """
        使用 SoM + LLM 消歧多个匹配

        Args:
            field: 字段定义
            matches: 匹配列表

        Returns:
            选中的匹配
        """
        # 构建候选列表
        candidates = []
        for i, match in enumerate(matches[:10]):  # 限制候选数量
            candidates.append(
                {
                    "mark_id": str(i + 1),
                    "text": match.text[:100],
                    "xpath": match.element_xpath,
                }
            )

        # 高亮候选元素 - 使用 JavaScript 临时高亮
        await self._highlight_candidates(candidates)

        # 截图
        _, screenshot_base64 = await capture_screenshot_with_marks(self.page)

        # 让 LLM 选择
        selection = await self.field_decider.select_correct_match(
            screenshot_base64=screenshot_base64,
            field=field,
            candidates=candidates,
        )

        # 清除高亮
        await self._clear_highlights()

        if selection and selection.get("action") == "select":
            args = selection.get("args") if isinstance(selection.get("args"), dict) else {}
            selected_mark_id = args.get("selected_mark_id")
            if selected_mark_id is None:
                items = args.get("items") or []
                if items and isinstance(items[0], dict):
                    selected_mark_id = items[0].get("mark_id")
            if selected_mark_id is None:
                selected_mark_id = args.get("mark_id")
            try:
                index = int(selected_mark_id) - 1
                if 0 <= index < len(matches):
                    return matches[index]
            except (ValueError, TypeError):
                pass

        return None

    def _select_best_url_match(self, matches: list[TextMatch], target_url: str) -> TextMatch | None:
        if not matches:
            return None
        ranked = sorted(
            matches,
            key=lambda m: self._score_url_match(m, target_url),
            reverse=True,
        )
        return ranked[0]

    def _score_url_match(self, match: TextMatch, target_url: str) -> float:
        score = float(match.similarity)
        tag = (match.element_tag or "").lower()
        attr = (match.source_attr or "").lower()
        text = (match.text or "").lower()
        content = (match.element_text_content or "").lower()

        if attr == "href":
            score += 0.2
        elif attr in {"src", "data-href"}:
            score += 0.1
        elif attr == "content":
            score -= 0.1

        if tag == "link":
            score += 0.25
        elif tag == "a":
            score += 0.2
        elif tag == "meta":
            score += 0.05
        else:
            score -= 0.05

        if "canonical" in content:
            score += 0.2
        if "detail.tmall.com/item.htm" in text:
            score += 0.1
        if target_url and target_url.lower() == text:
            score += 0.2
        if match.element_xpath.startswith("//*[@id="):
            score += 0.05
        return score

    def _merge_xpath_candidates(
        self,
        matches: list,
        selected_match,
    ) -> list[dict]:
        """合并多个 TextMatch 的 xpath_candidates

        策略：
        - 优先放选中匹配的多策略候选（id/class/data-* 锚点等）
        - 然后放其他匹配的主 XPath
        - 去重并限制总数
        """
        candidates: list[dict] = []
        seen: set[str] = set()
        priority_counter = 1

        # 首先：选中匹配的多策略候选
        if hasattr(selected_match, "xpath_candidates") and selected_match.xpath_candidates:
            for c in selected_match.xpath_candidates:
                xpath = c.get("xpath", "") if isinstance(c, dict) else ""
                if xpath and xpath not in seen:
                    seen.add(xpath)
                    candidates.append({
                        "xpath": xpath,
                        "priority": priority_counter,
                        "strategy": c.get("strategy", "unknown"),
                    })
                    priority_counter += 1
        else:
            # 兜底：如果没有多策略候选，至少加入主 XPath
            main_xpath = getattr(selected_match, "element_xpath", None)
            if main_xpath and main_xpath not in seen:
                seen.add(main_xpath)
                candidates.append({"xpath": main_xpath, "priority": priority_counter})
                priority_counter += 1

        # 然后：其他匹配的多策略候选
        for match in matches:
            if match is selected_match:
                continue
            if hasattr(match, "xpath_candidates") and match.xpath_candidates:
                for c in match.xpath_candidates:
                    xpath = c.get("xpath", "") if isinstance(c, dict) else ""
                    if xpath and xpath not in seen:
                        seen.add(xpath)
                        candidates.append({
                            "xpath": xpath,
                            "priority": priority_counter,
                            "strategy": c.get("strategy", "unknown"),
                        })
                        priority_counter += 1
            else:
                main_xpath = getattr(match, "element_xpath", None)
                if main_xpath and main_xpath not in seen:
                    seen.add(main_xpath)
                    candidates.append({"xpath": main_xpath, "priority": priority_counter})
                    priority_counter += 1

            if len(candidates) >= 20:
                break

        return candidates[:20]

    async def _select_best_verified_xpath(
        self,
        candidates: list[str],
        field: FieldDefinition,
        expected_value: str,
    ) -> str | None:
        """在候选 XPath 中选取“复查通过且更稳定”的表达式。"""
        unique_candidates: list[str] = []
        seen: set[str] = set()
        for xpath in candidates:
            value = (xpath or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            unique_candidates.append(value)

        best_xpath: str | None = None
        best_score = float("-inf")
        for xpath in unique_candidates[:8]:
            verified = await self._verify_xpath(
                xpath=xpath,
                field=field,
                expected_value=expected_value,
            )
            if not verified:
                continue
            stability = self._xpath_stability_score(xpath)
            if stability > best_score:
                best_score = stability
                best_xpath = xpath
        return best_xpath

    def _xpath_stability_score(self, xpath: str) -> float:
        """
        对 XPath 做稳定性评分。
        越依赖锚点属性（如 @id）分越高；越依赖深层数字索引分越低。
        对吸顶/浮层/弹窗等易波动节点做额外惩罚。
        """
        value = (xpath or "").strip()
        if not value:
            return -10.0

        lower = value.lower()
        score = 0.0
        if "@id=" in lower:
            score += 4.0
        if "@data-" in lower:
            score += 1.5
        if "@class" in lower:
            score += 0.8
        if lower.startswith("//*[@id="):
            score += 0.8

        numeric_index_count = len(re.findall(r"\[\d+\]", value))
        score -= numeric_index_count * 0.25

        depth = value.count("/")
        if depth > 10:
            score -= (depth - 10) * 0.08

        if "//" in value[2:] and "@id=" not in lower and "@class" not in lower:
            score -= 0.8

        volatile_tokens = ("fixed", "sticky", "float", "popup", "modal", "dialog", "mask")
        if any(token in lower for token in volatile_tokens):
            score -= 2.0

        if re.search(r'@id\s*=\s*["\'][^"\']*\d{6,}[^"\']*["\']', lower):
            score -= 0.6

        return score

    async def _highlight_candidates(self, candidates: list[dict]) -> None:
        """高亮候选元素"""
        js_code = """
        (candidates) => {
            // 清除之前的高亮
            document.querySelectorAll('[data-field-candidate]').forEach(el => {
                el.style.outline = '';
                el.removeAttribute('data-field-candidate');
            });
            
            // 添加新的高亮
            candidates.forEach((c, i) => {
                try {
                    const el = document.evaluate(c.xpath, document, null, 
                        XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                    if (el) {
                        el.style.outline = '3px solid red';
                        el.setAttribute('data-field-candidate', c.mark_id);
                    }
                } catch (e) {}
            });
        }
        """
        try:
            await self.page.evaluate(js_code, candidates)
        except Exception as e:
            logger.info(f"[FieldExtractor] 高亮候选元素失败: {e}")

    async def _clear_highlights(self) -> None:
        """清除高亮"""
        js_code = """
        () => {
            document.querySelectorAll('[data-field-candidate]').forEach(el => {
                el.style.outline = '';
                el.removeAttribute('data-field-candidate');
            });
        }
        """
        try:
            await self.page.evaluate(js_code)
        except Exception:
            pass

    async def _verify_xpath(
        self,
        xpath: str,
        field: FieldDefinition,
        expected_value: str,
    ) -> bool:
        """
        验证 XPath 是否能提取到预期值（含二次复查）

        Args:
            xpath: XPath 表达式
            field: 字段定义
            expected_value: 预期值

        Returns:
            验证是否通过
        """
        try:
            first_ok, first_value = await self._verify_xpath_once(
                xpath=xpath,
                field=field,
                expected_value=expected_value,
            )
            if not first_ok:
                return False

            # 复查：短暂等待后再次验证，避免 SPA 异步渲染导致的“瞬时命中”
            await asyncio.sleep(0.35)
            second_ok, second_value = await self._verify_xpath_once(
                xpath=xpath,
                field=field,
                expected_value=expected_value,
            )
            if not second_ok:
                return False

            if (
                first_value
                and second_value
                and self._normalize_text_for_compare(first_value)
                != self._normalize_text_for_compare(second_value)
            ):
                logger.info("[FieldExtractor] XPath 复查失败：两次提取值不一致")
                return False

            return True

        except Exception as e:
            logger.info(f"[FieldExtractor] XPath 验证异常: {e}")
            return False

    async def _verify_xpath_once(
        self,
        xpath: str,
        field: FieldDefinition,
        expected_value: str,
    ) -> tuple[bool, str | None]:
        """
        单次 XPath 验证：
        1) 存在性与范围检查
        2) 候选值匹配检查
        3) 数据类型语义检查
        4) 元素语义检查（避免按钮/导航等误命中）
        """
        locator = self.page.locator(f"xpath={xpath}")
        count = await locator.count()
        if count <= 0:
            return False, None

        # 命中范围过大通常意味着 XPath 过宽
        if count > 20:
            return False, None

        max_samples = min(count, 6)
        expected_normalized = self._normalize_text_for_compare(expected_value)
        dtype = (field.data_type or "text").lower()
        prefer_url = dtype == "url"

        matched_values: list[str] = []
        matched_tags: list[str] = []
        for idx in range(max_samples):
            node = locator.nth(idx)
            actual_value = await self._read_xpath_value(node, prefer_url=prefer_url)
            actual_value = (actual_value or "").strip()
            if not actual_value:
                continue

            actual_normalized = self._normalize_text_for_compare(actual_value)
            if expected_normalized:
                if (
                    expected_normalized in actual_normalized
                    or actual_normalized in expected_normalized
                ):
                    matched_values.append(actual_value)
                else:
                    similarity = self.fuzzy_searcher._calculate_similarity(
                        actual_value, expected_value
                    )
                    if similarity >= 0.8:
                        matched_values.append(actual_value)
            else:
                matched_values.append(actual_value)

            tag_name = await self._read_xpath_tag_name(node)
            if tag_name:
                matched_tags.append(tag_name)

        if not matched_values:
            return False, None

        normalized_matches = {
            self._normalize_text_for_compare(value) for value in matched_values if value
        }
        # 如果同一 XPath 命中多个“不同但都像正确答案”的值，视为范围过宽
        if len(normalized_matches) > 1:
            return False, None

        selected_value = matched_values[0]
        if not self._is_value_semantically_valid(selected_value, dtype):
            return False, None

        if self._is_xpath_semantically_suspicious(xpath, field, matched_tags):
            logger.info("[FieldExtractor] XPath 复查失败：元素语义可疑（按钮/导航）")
            return False, None

        return True, selected_value

    async def _read_xpath_value(self, element_locator, prefer_url: bool) -> str | None:
        try:
            if prefer_url:
                for attr in ("href", "src", "data-href"):
                    attr_val = await element_locator.get_attribute(attr, timeout=3000)
                    if attr_val and attr_val.strip():
                        return attr_val.strip()
            value = await element_locator.inner_text(timeout=3000)
            value = (value or "").strip()
            if value:
                return value
        except Exception:
            return None
        return None

    async def _read_xpath_tag_name(self, element_locator) -> str:
        try:
            value = await element_locator.evaluate("el => (el.tagName || '').toLowerCase()")
            return str(value or "").strip().lower()
        except Exception:
            return ""

    def _normalize_text_for_compare(self, value: str) -> str:
        return re.sub(r"\s+", " ", value or "").strip().lower()

    def _is_xpath_semantically_suspicious(
        self,
        xpath: str,
        field: FieldDefinition,
        matched_tags: list[str],
    ) -> bool:
        dtype = (field.data_type or "text").lower()
        if dtype == "url":
            return False

        interactive_tags = {"a", "button", "input", "select", "option", "label"}
        lower_xpath = (xpath or "").lower()
        if "/button" in lower_xpath or "/nav" in lower_xpath or "/header" in lower_xpath:
            return True

        if matched_tags and all(tag in interactive_tags for tag in matched_tags):
            return True
        return False

    def _is_value_semantically_valid(self, value: str, data_type: str) -> bool:
        text = (value or "").strip()
        if not text:
            return False

        if data_type == "url":
            return self._looks_like_url(text)
        if data_type == "number":
            return self._looks_like_number(text)
        if data_type == "date":
            return self._looks_like_date(text)
        return True

    def _looks_like_url(self, value: str) -> bool:
        text = (value or "").strip().lower()
        return bool(
            text.startswith("http://")
            or text.startswith("https://")
            or text.startswith("/")
        )

    def _looks_like_number(self, value: str) -> bool:
        return bool(re.fullmatch(r"[^\d\-+]*[-+]?\d[\d,\.\s]*[^\d]*", (value or "").strip()))

    def _looks_like_date(self, value: str) -> bool:
        text = (value or "").strip()
        patterns = [
            r"\d{4}[-/年]\d{1,2}([-/月]\d{1,2}日?)?",
            r"\d{1,2}[-/]\d{1,2}([-/]\d{2,4})?",
        ]
        return any(re.search(p, text) for p in patterns)
