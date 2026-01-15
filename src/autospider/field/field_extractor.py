"""核心字段提取器

实现从详情页提取目标字段的完整流程：
1. 导航阶段：使用 SoM + LLM 定位目标字段
2. 提取阶段：LLM 识别 → HTML 模糊搜索 → 消歧
3. XPath 提取和验证
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ..common.som import (
    inject_and_scan,
    capture_screenshot_with_marks,
    clear_overlay,
    build_mark_id_to_xpath_map,
    format_marks_for_llm,
)
from ..common.som.text_first import resolve_single_mark_id
from ..common.browser import ActionExecutor
from ..common.types import Action, ActionType
from ..common.config import config
from ..common.utils.fuzzy_search import FuzzyTextSearcher, TextMatch
from ..extractor.llm import LLMDecider

from .models import (
    FieldDefinition,
    FieldExtractionResult,
    PageExtractionRecord,
)
from .field_decider import FieldDecider

if TYPE_CHECKING:
    from playwright.async_api import Page


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
            mark_id = decision.get("mark_id")
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
            mark_id = decision.get("mark_id")
            try:
                clicked.add(int(mark_id))
            except (TypeError, ValueError):
                continue
        return clicked

    async def _get_full_page_html(self) -> str:
        try:
            return await self.page.content()
        except Exception as e:
            print(f"[FieldExtractor] 获取页面 HTML 失败: {e}")
            return await self.page.inner_text("body")
    
    async def extract_from_url(self, url: str) -> PageExtractionRecord:
        """
        从单个 URL 提取所有字段
        
        Args:
            url: 详情页 URL
            
        Returns:
            页面提取记录
        """
        print(f"\n{'='*60}")
        print(f"[FieldExtractor] 开始提取: {url}")
        print(f"[FieldExtractor] 目标字段: {[f.name for f in self.fields]}")
        print(f"{'='*60}\n")
        
        record = PageExtractionRecord(url=url)
        
        try:
            # 导航到页面
            await self.page.goto(url, wait_until="domcontentloaded")
            await asyncio.sleep(1.5)  # 等待页面加载
            
            # 提取每个字段
            for field in self.fields:
                print(f"\n[FieldExtractor] --- 提取字段: {field.name} ---")
                result = await self._extract_single_field(field, record.nav_steps)
                record.fields.append(result)
                
                if result.value:
                    print(f"[FieldExtractor] ✓ 字段 '{field.name}' 提取成功: {result.value[:50]}...")
                else:
                    print(f"[FieldExtractor] ✗ 字段 '{field.name}' 提取失败: {result.error}")
            
            # 检查是否所有必填字段都提取成功
            required_fields_ok = all(
                record.get_field_value(f.name) is not None
                for f in self.fields if f.required
            )
            record.success = required_fields_ok
            
        except Exception as e:
            print(f"[FieldExtractor] 提取异常: {e}")
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
        might_contain = await self.field_decider.check_field_in_page_text(
            html_content, field
        )

        if might_contain:
            _, screenshot_base64 = await capture_screenshot_with_marks(self.page)
            extract_result = await self.field_decider.extract_field_text(
                screenshot_base64=screenshot_base64,
                field=field,
            )
            if extract_result and extract_result.get("found"):
                field_text = extract_result.get("field_value")
                result.confidence = extract_result.get("confidence", 0.8)
                await self._finalize_extraction(result, field, field_text)
                return result

        # 阶段 1：导航到目标字段
        nav_result = await self._navigate_to_field(field, nav_steps)
        
        if nav_result is None:
            result.error = "导航阶段未找到字段"
            return result
        
        if nav_result.get("action") == "field_not_exist":
            result.error = f"字段不存在: {nav_result.get('reasoning', '')}"
            return result
        
        # 阶段 2：提取字段值
        field_text = nav_result.get("field_text") or nav_result.get("field_value")
        
        if not field_text:
            # 如果导航阶段没有直接返回文本，再次调用 LLM 提取
            _, screenshot_base64 = await capture_screenshot_with_marks(self.page)
            extract_result = await self.field_decider.extract_field_text(
                screenshot_base64=screenshot_base64,
                field=field,
            )
            
            if extract_result and extract_result.get("found"):
                field_text = extract_result.get("field_value")
                result.confidence = extract_result.get("confidence", 0.8)
        
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

            if result.xpath:
                verified = await self._verify_xpath(result.xpath, field_text)
                if verified:
                    result.confidence = max(result.confidence, 0.9)
                    print(f"[FieldExtractor] XPath 验证通过: {result.xpath}")
                else:
                    print(f"[FieldExtractor] XPath 验证失败，使用 LLM 提取的值")
    
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
            print(f"[FieldExtractor] 导航步骤 {step + 1}/{self.max_nav_steps}")
            
            # 获取 SoM 快照
            snapshot = await inject_and_scan(self.page)
            _, screenshot_base64 = await capture_screenshot_with_marks(self.page)
            
            html_content = await self._get_full_page_html()
            might_contain = await self.field_decider.check_field_in_page_text(
                html_content, field
            )
            
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
                print(f"[FieldExtractor] LLM 决策失败，继续尝试")
                continue

            action = decision.get("action")

            if action == "scroll_down" and not might_contain:
                clicked_ids = self._get_clicked_mark_ids(nav_steps, field.name)
                candidates = self.field_decider.get_clickable_candidate_ids(
                    snapshot, exclude_ids=clicked_ids, max_candidates=5
                )
                if candidates:
                    action = "click"
                    decision["action"] = "click"
                    decision["mark_id"] = candidates[0]
            
            # 记录导航步骤
            nav_steps.append({
                "step": step + 1,
                "action": action,
                "field_name": field.name,
                "decision": decision,
                "url": self.page.url,
            })
            
            # 处理不同的决策
            if action == "found_field":
                print(f"[FieldExtractor] ✓ 找到字段: {decision.get('field_text', '')[:50]}...")
                await clear_overlay(self.page)
                return decision
            
            elif action == "field_not_exist":
                print(f"[FieldExtractor] ✗ 字段不存在")
                await clear_overlay(self.page)
                return decision
            
            elif action == "click":
                mark_id_raw = decision.get("mark_id")
                target_text = decision.get("target_text") or ""
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
                mark_id = decision.get("mark_id")
                target_text = decision.get("target_text") or ""
                text = decision.get("text")
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
                        print(f"[FieldExtractor] 输入动作 mark_id 无效: {mark_id}")
                else:
                    print(f"[FieldExtractor] 输入动作缺少 mark_id 或 text")
                await asyncio.sleep(0.5)

            elif action == "press":
                key = decision.get("key") or "Enter"
                mark_id = decision.get("mark_id")
                target_text = decision.get("target_text") or ""
                mark_id_value = None
                if mark_id is not None:
                    try:
                        mark_id_value = int(mark_id)
                    except (TypeError, ValueError):
                        print(f"[FieldExtractor] 按键动作 mark_id 无效: {mark_id}")

                if config.url_collector.validate_mark_id and target_text:
                    mark_id_value = await resolve_single_mark_id(
                        page=self.page,
                        llm=self.llm_decider.llm,
                        snapshot=snapshot,
                        mark_id=mark_id_value,
                        target_text=target_text,
                        max_retries=config.url_collector.max_validation_retries,
                    )
                await self._execute_press(key, mark_id_value, snapshot)
                await asyncio.sleep(0.5)
            
            elif action == "scroll_down":
                await self.page.evaluate("window.scrollBy(0, 500)")
                await asyncio.sleep(0.5)
            
            else:
                print(f"[FieldExtractor] 未知操作: {action}")
            
            # 清除 SoM 覆盖层
            await clear_overlay(self.page)
        
        print(f"[FieldExtractor] 达到最大导航步数 {self.max_nav_steps}")
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
            print(f"[FieldExtractor] 点击失败: {e}")
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
            print(f"[FieldExtractor] 输入失败: {e}")
            return False

    async def _execute_press(self, key: str, mark_id: int | None, snapshot) -> bool:
        """执行按键操作"""
        try:
            mark_id_to_xpath = build_mark_id_to_xpath_map(snapshot)

            action = Action(
                action=ActionType.PRESS,
                mark_id=mark_id,
                key=key,
            )

            result, _ = await self.action_executor.execute(
                action=action,
                mark_id_to_xpath=mark_id_to_xpath,
                step_index=0,
            )

            return result.success
        except Exception as e:
            print(f"[FieldExtractor] 按键失败: {e}")
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
        print(f"[FieldExtractor] 在 HTML 中搜索: '{target_text[:30]}...'")
        
        # 获取页面 HTML
        html_content = await self.page.content()
        
        # 模糊搜索
        matches = self.fuzzy_searcher.search_in_html(html_content, target_text)
        
        if not matches:
            print(f"[FieldExtractor] HTML 中未找到匹配")
            return None
        
        print(f"[FieldExtractor] 找到 {len(matches)} 个匹配")
        
        if len(matches) == 1:
            # 唯一匹配，直接使用
            match = matches[0]
            print(f"[FieldExtractor] 唯一匹配: xpath={match.element_xpath}")
            return {
                "xpath": match.element_xpath,
                "xpath_candidates": [{"xpath": match.element_xpath, "priority": 1}],
                "match": match,
            }
        
        # 多个匹配，需要消歧
        print(f"[FieldExtractor] 多个匹配，启动消歧流程")
        selected_match = await self._disambiguate_matches(field, matches)
        
        if selected_match:
            return {
                "xpath": selected_match.element_xpath,
                "xpath_candidates": [
                    {"xpath": m.element_xpath, "priority": i + 1}
                    for i, m in enumerate(matches)
                ],
                "match": selected_match,
            }
        
        # 消歧失败，使用第一个匹配
        return {
            "xpath": matches[0].element_xpath,
            "xpath_candidates": [
                {"xpath": m.element_xpath, "priority": i + 1}
                for i, m in enumerate(matches)
            ],
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
            candidates.append({
                "mark_id": str(i + 1),
                "text": match.text[:100],
                "xpath": match.element_xpath,
            })
        
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
        
        if selection:
            selected_mark_id = selection.get("selected_mark_id")
            try:
                index = int(selected_mark_id) - 1
                if 0 <= index < len(matches):
                    return matches[index]
            except (ValueError, TypeError):
                pass
        
        return None
    
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
            print(f"[FieldExtractor] 高亮候选元素失败: {e}")
    
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
    
    async def _verify_xpath(self, xpath: str, expected_value: str) -> bool:
        """
        验证 XPath 是否能提取到预期值
        
        Args:
            xpath: XPath 表达式
            expected_value: 预期值
            
        Returns:
            验证是否通过
        """
        try:
            # 使用 XPath 提取值
            element = self.page.locator(f"xpath={xpath}").first
            actual_value = await element.inner_text(timeout=3000)
            
            # 标准化比较
            actual_normalized = actual_value.strip().lower()
            expected_normalized = expected_value.strip().lower()
            
            # 检查是否包含或相似
            if expected_normalized in actual_normalized:
                return True
            if actual_normalized in expected_normalized:
                return True
            
            # 使用模糊匹配
            similarity = self.fuzzy_searcher._calculate_similarity(
                actual_value, expected_value
            )
            return similarity >= 0.8
            
        except Exception as e:
            print(f"[FieldExtractor] XPath 验证异常: {e}")
            return False
