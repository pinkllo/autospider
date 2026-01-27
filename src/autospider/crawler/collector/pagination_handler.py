"""分页处理模块 - 负责分页控件识别和翻页操作"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from ...common.config import config
from ...common.browser.actions import ActionExecutor
from ...common.som import (
    build_mark_id_to_xpath_map,
    capture_screenshot_with_marks,
    clear_overlay,
    inject_and_scan,
)
from ...common.som.text_first import resolve_single_mark_id
from ...common.types import Action, ActionType
from ...common.protocol import coerce_bool

if TYPE_CHECKING:
    from pathlib import Path
    from playwright.async_api import Page
    from .llm_decision import LLMDecisionMaker


class PaginationHandler:
    """分页处理器，负责识别和操作分页控件"""

    def __init__(
        self,
        page: "Page",
        list_url: str,
        screenshots_dir: "Path" = None,
        llm_decision_maker: "LLMDecisionMaker" = None,
    ):
        self.page = page
        self.list_url = list_url
        self.screenshots_dir = screenshots_dir
        self.llm_decision_maker = llm_decision_maker
        self.pagination_xpath: str | None = None
        self.current_page_num = 1
        self.jump_widget_xpath: dict[str, str] | None = None  # {"input": "...", "button": "..."}"

    async def extract_pagination_xpath(self) -> str | None:
        """
        在探索阶段提取分页控件的 xpath

        策略：先用 LLM 视觉识别，失败则使用增强的规则兜底
        """
        print("[Extract-Pagination] 开始提取分页控件 xpath...")

        # 策略1: 优先使用 LLM 视觉识别（准确度更高）
        if self.llm_decision_maker:
            print("[Extract-Pagination] 策略1: 使用 LLM 视觉识别...")
            result = await self.extract_pagination_xpath_with_llm()
            if result:
                print(f"[Extract-Pagination] ✓ LLM 识别成功: {result}")
                return result
            print("[Extract-Pagination] LLM 识别失败，切换到规则兜底...")

        # 策略2: 规则兜底 - 增强的分页按钮选择器
        print("[Extract-Pagination] 策略2: 使用规则识别...")
        common_selectors = [
            # 中文文本匹配
            'a:has-text("下一页")',
            'button:has-text("下一页")',
            'a:has-text("下页")',
            'span:has-text("下一页") >> xpath=ancestor::a',
            'span:has-text("下一页") >> xpath=ancestor::button',
            # 英文文本匹配
            'a:has-text("Next")',
            'button:has-text("Next")',
            'a:has-text("next")',
            'button:has-text("next")',
            # 符号匹配
            'a:has-text(">")',
            'button:has-text(">")',
            'a:has-text("›")',
            'a:has-text("»")',
            # 图标按钮匹配（纯图标，无文本）
            "button:has(.icon-right):not([disabled])",
            'button:has([class*="icon-right"]):not([disabled])',
            "a:has(.icon-right)",
            'a:has([class*="icon-right"])',
            "button:has(.icon-next):not([disabled])",
            'button:has([class*="icon-next"]):not([disabled])',
            "a:has(.icon-next)",
            # 常见图标库的右箭头/下一页图标
            "button:has(.gd-icon.icon-right):not([disabled])",  # GD Design
            "button:has(.el-icon-arrow-right):not([disabled])",  # Element UI
            "button:has(.el-icon-d-arrow-right):not([disabled])",
            "a:has(.el-icon-arrow-right)",
            "button:has(.anticon-right):not([disabled])",  # Ant Design
            "button:has(.anticon-double-right):not([disabled])",
            "a:has(.anticon-right)",
            "button:has(.fa-chevron-right):not([disabled])",  # Font Awesome
            "button:has(.fa-angle-right):not([disabled])",
            "button:has(.fa-arrow-right):not([disabled])",
            "a:has(.fa-chevron-right)",
            'button:has(svg[class*="right"]):not([disabled])',  # SVG 图标
            'a:has(svg[class*="right"])',
            # 类名匹配（排除disabled状态）
            '[class*="next"]:not([class*="disabled"]):not([disabled])',
            '[class*="Next"]:not([class*="disabled"]):not([disabled])',
            'a[class*="page-next"]:not([class*="disabled"])',
            'button[class*="page-next"]:not([class*="disabled"])',
            'button[class*="icon-only"]:has([class*="right"]):not([disabled])',
            # ID 匹配
            "#next-page",
            "#nextPage",
            'a[id*="next"]',
            'button[id*="next"]',
            # aria-label 匹配
            'a[aria-label*="next" i]',
            'button[aria-label*="next" i]',
            'a[aria-label*="下一页"]',
            'button[aria-label*="下一页"]',
            'button[aria-label*="右" i]',
            # 分页容器中的最后一个链接/按钮
            '[class*="pagination"] a:not([class*="disabled"]):last-child',
            '[class*="pagination"] button:not([class*="disabled"]):not([disabled]):last-child',
            '[class*="pager"] a:not([class*="disabled"]):last-child',
            '[class*="pager"] button:not([class*="disabled"]):not([disabled]):last-child',
            ".pagination > li:last-child > a",
            ".pagination > li:last-child > button",
            ".pager > li:last-child > a",
            ".pager > li:last-child > button",
            # rel="next" 属性
            'a[rel="next"]',
            # title 属性匹配
            'a[title*="下一页"]',
            'button[title*="下一页"]',
            'a[title*="next" i]',
            'button[title*="next" i]',
        ]

        for selector in common_selectors:
            try:
                locator = self.page.locator(selector)
                count = await locator.count()
                if count > 0:
                    # 验证元素是否可见且可点击
                    first_elem = locator.first
                    if await first_elem.is_visible():
                        print(f"[Extract-Pagination] ✓ 规则识别成功: {selector}")
                        self.pagination_xpath = selector
                        return selector
            except Exception:
                continue

        print("[Extract-Pagination] ⚠ 所有策略均失败，未能提取分页控件")
        return None

    async def extract_jump_widget_xpath(self) -> dict[str, str] | None:
        """
        提取页码跳转控件的 xpath（输入框 + 确定按钮）

        用于断点恢复的第二阶段策略（控件直达）

        策略：先用 LLM 视觉识别，失败则使用增强的规则兜底

        Returns:
            {"input": "输入框xpath", "button": "按钮xpath"} 或 None
        """
        print("[Extract-JumpWidget] 开始提取页码跳转控件...")

        # 策略1: 优先使用 LLM 视觉识别（准确度更高）
        if self.llm_decision_maker:
            print("[Extract-JumpWidget] 策略1: 使用 LLM 视觉识别...")
            result = await self._extract_jump_widget_with_llm()
            if result:
                print(f"[Extract-JumpWidget] ✓ LLM 识别成功: {result}")
                self.jump_widget_xpath = result
                return result
            print("[Extract-JumpWidget] LLM 识别失败，切换到规则兜底...")

        # 策略2: 规则兜底
        print("[Extract-JumpWidget] 策略2: 使用规则识别...")
        input_xpath = None
        button_xpath = None

        # 常见的页码输入框选择器
        input_selectors = [
            'input[type="text"][placeholder*="页" i]',
            'input[type="number"][placeholder*="页" i]',
            'input[type="text"][placeholder*="page" i]',
            'input[type="number"][placeholder*="page" i]',
            'input[class*="page-input"]',
            'input[class*="pageInput"]',
            'input[class*="jump"]',
            'input[class*="go-input"]',
            'input[id*="page" i]',
            'input[id*="jump" i]',
            '[class*="pagination"] input[type="text"]',
            '[class*="pagination"] input[type="number"]',
            '[class*="pager"] input[type="text"]',
            '[class*="pager"] input[type="number"]',
            ".pagination input",
            ".pager input",
        ]

        # 常见的确定/跳转按钮选择器
        button_selectors = [
            'button:has-text("确定")',
            'button:has-text("确认")',
            'button:has-text("跳转")',
            'button:has-text("GO")',
            'button:has-text("Go")',
            'button:has-text("go")',
            'a:has-text("确定")',
            'a:has-text("GO")',
            'button[class*="page-go"]',
            'button[class*="jump"]',
            'button[class*="confirm"]',
            'a[class*="page-go"]',
            'button[id*="go" i]',
            'button[id*="jump" i]',
            'button[id*="confirm" i]',
            '[class*="pagination"] button',
            '[class*="pager"] button',
        ]

        for selector in input_selectors:
            try:
                locator = self.page.locator(selector)
                if await locator.count() > 0 and await locator.first.is_visible():
                    input_xpath = selector
                    print(f"[Extract-JumpWidget] ✓ 找到输入框: {selector}")
                    break
            except Exception:
                continue

        if input_xpath:
            for selector in button_selectors:
                try:
                    locator = self.page.locator(selector)
                    if await locator.count() > 0 and await locator.first.is_visible():
                        button_xpath = selector
                        print(f"[Extract-JumpWidget] ✓ 找到按钮: {selector}")
                        break
                except Exception:
                    continue

        if input_xpath and button_xpath:
            self.jump_widget_xpath = {"input": input_xpath, "button": button_xpath}
            print("[Extract-JumpWidget] ✓ 成功提取跳转控件")
            return self.jump_widget_xpath
        else:
            print("[Extract-JumpWidget] ⚠ 未能提取完整的跳转控件")
            return None

    async def _extract_jump_widget_with_llm(self) -> dict[str, str] | None:
        """使用 LLM 视觉识别跳转控件并提取 xpath"""
        if not self.llm_decision_maker:
            return None

        try:
            await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(0.5)

            await clear_overlay(self.page)
            snapshot = await inject_and_scan(self.page)
            screenshot_bytes, screenshot_base64 = await capture_screenshot_with_marks(self.page)

            if self.screenshots_dir:
                screenshot_path = self.screenshots_dir / "jump_widget_extract.png"
                screenshot_path.write_bytes(screenshot_bytes)

            data = await self.llm_decision_maker.extract_jump_widget_with_llm(
                snapshot, screenshot_base64
            )

            args = data.get("args") if isinstance(data, dict) and isinstance(data.get("args"), dict) else {}
            purpose = (args.get("purpose") or "").lower()
            found = coerce_bool(args.get("found"), default=True)

            if data and data.get("action") == "select" and purpose in {"jump_widget", "page_jump"} and found:
                input_obj = args.get("input") if isinstance(args.get("input"), dict) else {}
                button_obj = args.get("button") if isinstance(args.get("button"), dict) else {}
                input_mark_id = input_obj.get("mark_id")
                button_mark_id = button_obj.get("mark_id")
                input_text = input_obj.get("text") or ""
                button_text = button_obj.get("text") or ""

                print(
                    f"[Extract-JumpWidget-LLM] 找到输入框 [{input_mark_id}], 按钮 [{button_mark_id}]"
                )

                input_xpath = None
                button_xpath = None

                if input_mark_id:
                    try:
                        input_mark_id_value = int(input_mark_id)
                    except (TypeError, ValueError):
                        input_mark_id_value = None

                    # 修改原因：全项目统一“文本优先纠正 mark_id”，输入框常见 innerText 为空，需要依赖 placeholder/aria-label
                    if config.url_collector.validate_mark_id and input_text:
                        input_mark_id_value = await resolve_single_mark_id(
                            page=self.page,
                            llm=self.llm_decision_maker.decider.llm,
                            snapshot=snapshot,
                            mark_id=input_mark_id_value,
                            target_text=input_text,
                            max_retries=config.url_collector.max_validation_retries,
                        )

                    element = (
                        next(
                            (m for m in snapshot.marks if m.mark_id == int(input_mark_id_value)),
                            None,
                        )
                        if input_mark_id_value is not None
                        else None
                    )
                    if element and element.xpath_candidates:
                        sorted_candidates = sorted(
                            element.xpath_candidates, key=lambda x: x.priority
                        )
                        input_xpath = sorted_candidates[0].xpath if sorted_candidates else None

                if button_mark_id:
                    try:
                        button_mark_id_value = int(button_mark_id)
                    except (TypeError, ValueError):
                        button_mark_id_value = None

                    if config.url_collector.validate_mark_id and button_text:
                        button_mark_id_value = await resolve_single_mark_id(
                            page=self.page,
                            llm=self.llm_decision_maker.decider.llm,
                            snapshot=snapshot,
                            mark_id=button_mark_id_value,
                            target_text=button_text,
                            max_retries=config.url_collector.max_validation_retries,
                        )

                    element = (
                        next(
                            (m for m in snapshot.marks if m.mark_id == int(button_mark_id_value)),
                            None,
                        )
                        if button_mark_id_value is not None
                        else None
                    )
                    if element and element.xpath_candidates:
                        sorted_candidates = sorted(
                            element.xpath_candidates, key=lambda x: x.priority
                        )
                        button_xpath = sorted_candidates[0].xpath if sorted_candidates else None

                if input_xpath and button_xpath:
                    return {"input": input_xpath, "button": button_xpath}
                elif input_xpath:
                    print("[Extract-JumpWidget-LLM] 找到输入框但未找到按钮的 xpath")
                    return None
            else:
                reasoning = args.get("reasoning") if isinstance(args, dict) else ""
                print(
                    f"[Extract-JumpWidget-LLM] 未找到跳转控件: {reasoning if data else ''}"
                )
        except Exception as e:
            print(f"[Extract-JumpWidget-LLM] LLM 识别失败: {e}")

        return None

    async def extract_pagination_xpath_with_llm(self) -> str | None:
        """使用 LLM 视觉识别分页控件并提取 xpath"""
        if not self.llm_decision_maker:
            return None

        try:
            await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(0.5)

            await clear_overlay(self.page)
            snapshot = await inject_and_scan(self.page)
            screenshot_bytes, screenshot_base64 = await capture_screenshot_with_marks(self.page)

            # 保存截图
            if self.screenshots_dir:
                screenshot_path = self.screenshots_dir / "pagination_extract.png"
                screenshot_path.write_bytes(screenshot_bytes)

            # 使用 LLM 识别分页控件
            data = await self.llm_decision_maker.extract_pagination_with_llm(
                snapshot, screenshot_base64
            )

            args = data.get("args") if isinstance(data, dict) and isinstance(data.get("args"), dict) else {}
            purpose = (args.get("purpose") or "").lower()
            found = coerce_bool(args.get("found"), default=True)
            item = None
            items = args.get("items") or []
            if items and isinstance(items[0], dict):
                item = items[0]

            mark_id_raw = None
            target_text = ""
            if item:
                mark_id_raw = item.get("mark_id")
                target_text = item.get("text") or ""
            if mark_id_raw is None:
                mark_id_raw = args.get("mark_id")
                target_text = target_text or (args.get("target_text") or "")

            if data and data.get("action") == "select" and purpose in {"pagination_next", "next_page"} and found and mark_id_raw is not None:
                reasoning = args.get("reasoning") or ""
                print(
                    f"[Extract-Pagination-LLM] 找到分页按钮 [{mark_id_raw}]: {reasoning}"
                )

                try:
                    mark_id_value = int(mark_id_raw)
                except (TypeError, ValueError):
                    mark_id_value = None

                # 修改原因：分页按钮很容易把页面上的“>”等符号误认为编号，统一用文本优先纠正
                if config.url_collector.validate_mark_id and target_text:
                    mark_id_value = await resolve_single_mark_id(
                        page=self.page,
                        llm=self.llm_decision_maker.decider.llm,
                        snapshot=snapshot,
                        mark_id=mark_id_value,
                        target_text=target_text,
                        max_retries=config.url_collector.max_validation_retries,
                    )

                # 找到对应的元素，获取其 xpath
                element = next((m for m in snapshot.marks if m.mark_id == mark_id_value), None)
                if element and element.xpath_candidates:
                    # 取优先级最高的 xpath
                    sorted_candidates = sorted(element.xpath_candidates, key=lambda x: x.priority)
                    best_xpath = sorted_candidates[0].xpath if sorted_candidates else None

                    if best_xpath:
                        self.pagination_xpath = best_xpath
                        print(f"[Extract-Pagination-LLM] ✓ 提取到 xpath: {best_xpath}")
                        return best_xpath
            else:
                reasoning = args.get("reasoning") if isinstance(args, dict) else ""
                print(
                    f"[Extract-Pagination-LLM] 未找到分页按钮: {reasoning if data else ''}"
                )
        except Exception as e:
            print(f"[Extract-Pagination-LLM] LLM 识别失败: {e}")

        print("[Extract-Pagination] ⚠ 未能提取分页控件 xpath")
        return None

    async def find_and_click_next_page(self) -> bool:
        """
        查找并点击下一页按钮

        策略优先级：
        1. 使用提取的 pagination_xpath（探索阶段识别的）
        2. 使用 LLM 实时视觉识别
        3. 使用增强的规则兜底

        Returns:
            是否成功翻页
        """
        # 策略1: 使用提取的 pagination_xpath
        if self.pagination_xpath:
            try:
                # 检查是否是 xpath
                if self.pagination_xpath.startswith("//") or self.pagination_xpath.startswith("("):
                    locator = self.page.locator(f"xpath={self.pagination_xpath}")
                else:
                    locator = self.page.locator(self.pagination_xpath)

                if await locator.count() > 0 and await locator.first.is_visible():
                    print("[Pagination] 策略1: 使用提取的 xpath...")

                    # 获取随机延迟
                    from ...common.utils.delay import get_random_delay

                    delay = get_random_delay(
                        config.url_collector.action_delay_base,
                        config.url_collector.action_delay_random,
                    )
                    await asyncio.sleep(delay)

                    await locator.first.click(timeout=5000)
                    await asyncio.sleep(config.url_collector.page_load_delay)

                    self.current_page_num += 1
                    print(f"[Pagination] ✓ 翻页成功，当前第 {self.current_page_num} 页")
                    return True
            except Exception as e:
                print(f"[Pagination] 策略1 失败: {e}")

        # 策略2: 使用 LLM 实时视觉识别
        if self.llm_decision_maker:
            print("[Pagination] 策略2: 使用 LLM 视觉识别...")
            try:
                result = await self.find_next_page_with_llm()
                if result:
                    return True
                print("[Pagination] LLM 识别失败，切换到规则兜底...")
            except Exception as e:
                print(f"[Pagination] 策略2 失败: {e}")

        # 策略3: 增强的规则兜底
        print("[Pagination] 策略3: 使用规则识别...")
        common_selectors = [
            # 中文文本
            'a:has-text("下一页")',
            'button:has-text("下一页")',
            'a:has-text("下页")',
            # 英文文本
            'a:has-text("Next")',
            'button:has-text("Next")',
            'a:has-text("next")',
            'button:has-text("next")',
            # 符号
            'a:has-text(">")',
            'button:has-text(">")',
            'a:has-text("›")',
            'a:has-text("»")',
            # 图标按钮（纯图标，无文本）
            "button:has(.icon-right):not([disabled])",
            'button:has([class*="icon-right"]):not([disabled])',
            "a:has(.icon-right)",
            "button:has(.icon-next):not([disabled])",
            "button:has(.gd-icon.icon-right):not([disabled])",
            "button:has(.el-icon-arrow-right):not([disabled])",
            "button:has(.anticon-right):not([disabled])",
            "button:has(.fa-chevron-right):not([disabled])",
            'button:has(svg[class*="right"]):not([disabled])',
            # 类名
            '[class*="next"]:not([class*="disabled"]):not([disabled])',
            '[class*="Next"]:not([class*="disabled"]):not([disabled])',
            'a[class*="page-next"]:not([class*="disabled"])',
            'button[class*="icon-only"]:has([class*="right"]):not([disabled])',
            # ID
            "#next-page",
            "#nextPage",
            # aria-label
            'a[aria-label*="next" i]',
            'button[aria-label*="next" i]',
            'a[aria-label*="下一页"]',
            'button[aria-label*="右" i]',
            # 分页容器
            '[class*="pagination"] a:not([class*="disabled"]):last-child',
            '[class*="pagination"] button:not([class*="disabled"]):not([disabled]):last-child',
            ".pagination > li:last-child > a",
            ".pagination > li:last-child > button",
            # rel 属性
            'a[rel="next"]',
        ]

        for selector in common_selectors:
            try:
                locator = self.page.locator(selector)
                count = await locator.count()
                if count > 0:
                    first_elem = locator.first
                    # 检查可见性
                    is_visible = await first_elem.is_visible()
                    if is_visible:
                        print(f"[Pagination] 规则匹配: {selector} (共{count}个元素)")

                        from ...common.utils.delay import get_random_delay

                        delay = get_random_delay(
                            config.url_collector.action_delay_base,
                            config.url_collector.action_delay_random,
                        )
                        await asyncio.sleep(delay)

                        # 尝试点击
                        await first_elem.click(timeout=5000)
                        await asyncio.sleep(config.url_collector.page_load_delay)

                        self.current_page_num += 1
                        print(f"[Pagination] ✓ 翻页成功，当前第 {self.current_page_num} 页")
                        return True
            except Exception as e:
                print(f"[Pagination] 规则 '{selector}' 失败: {e}")
                continue

        print("[Pagination] ⚠ 所有策略均失败，未找到下一页按钮")
        return False

    async def find_next_page_with_llm(self, screenshot_base64: str = None) -> bool:
        """
        使用 LLM 视觉识别并点击下一页按钮

        Returns:
            是否成功翻页
        """
        if not self.llm_decision_maker:
            return False

        try:
            # 如果没有提供截图，重新截图
            if not screenshot_base64:
                await clear_overlay(self.page)
                snapshot = await inject_and_scan(self.page)
                screenshot_bytes, screenshot_base64 = await capture_screenshot_with_marks(self.page)
            else:
                snapshot = await inject_and_scan(self.page)

            # 使用 LLM 识别下一页按钮
            data = await self.llm_decision_maker.extract_pagination_with_llm(
                snapshot, screenshot_base64
            )

            args = data.get("args") if isinstance(data, dict) and isinstance(data.get("args"), dict) else {}
            purpose = (args.get("purpose") or "").lower()
            found = coerce_bool(args.get("found"), default=True)
            item = None
            items = args.get("items") or []
            if items and isinstance(items[0], dict):
                item = items[0]

            mark_id_raw = None
            target_text = ""
            if item:
                mark_id_raw = item.get("mark_id")
                target_text = item.get("text") or ""
            if mark_id_raw is None:
                mark_id_raw = args.get("mark_id")
                target_text = target_text or (args.get("target_text") or "")

            if data and data.get("action") == "select" and purpose in {"pagination_next", "next_page"} and found and mark_id_raw is not None:
                print(f"[Pagination-LLM] 找到下一页按钮 [{mark_id_raw}]")

                try:
                    mark_id_value = int(mark_id_raw)
                except (TypeError, ValueError):
                    mark_id_value = None

                if config.url_collector.validate_mark_id and target_text:
                    mark_id_value = await resolve_single_mark_id(
                        page=self.page,
                        llm=self.llm_decision_maker.decider.llm,
                        snapshot=snapshot,
                        mark_id=mark_id_value,
                        target_text=target_text,
                        max_retries=config.url_collector.max_validation_retries,
                    )

                if mark_id_value is None:
                    print(f"[Pagination-LLM] mark_id 无效，无法点击: {mark_id_raw}")
                    return False

                mark_id_to_xpath = build_mark_id_to_xpath_map(snapshot)
                executor = ActionExecutor(self.page)

                print(f"[Pagination-LLM] 尝试点击 mark_id={mark_id_value}...")
                from ...common.utils.delay import get_random_delay

                delay = get_random_delay(
                    config.url_collector.action_delay_base,
                    config.url_collector.action_delay_random,
                )
                await asyncio.sleep(delay)

                result, _ = await executor.execute(
                    Action(
                        action=ActionType.CLICK,
                        mark_id=mark_id_value,
                        target_text=target_text or None,
                        timeout_ms=5000,
                    ),
                    mark_id_to_xpath,
                    step_index=0,
                )

                new_page = getattr(executor, "_new_page", None)
                if new_page is not None:
                    # Pagination should not open a new tab. Close it to avoid leaking pages.
                    try:
                        await new_page.close()
                    except Exception:
                        pass
                    executor._new_page = None
                    print("[Pagination-LLM] Unexpected new tab opened; treat as failure.")
                    return False

                if not result.success:
                    print(f"[Pagination-LLM] 点击失败: {result.error}")
                    return False

                await asyncio.sleep(config.url_collector.page_load_delay)
                self.current_page_num += 1
                print(f"[Pagination-LLM] ✓ 翻页成功，当前第 {self.current_page_num} 页")
                return True
            else:
                reasoning = args.get("reasoning") if isinstance(args, dict) else ""
                print(f"[Pagination-LLM] 未找到下一页: {reasoning if data else ''}")
        except Exception as e:
            print(f"[Pagination-LLM] LLM 识别失败: {e}")

        return False
