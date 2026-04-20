"""分页处理模块 - 负责分页控件识别和翻页操作"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from autospider.platform.browser.actions import ActionExecutor
from autospider.platform.config.runtime import config
from autospider.platform.observability.logger import get_logger
from autospider.platform.llm.protocol import coerce_bool
from autospider.platform.browser.som import (
    build_mark_id_to_xpath_map,
    capture_screenshot_with_marks,
    clear_overlay,
    inject_and_scan,
)
from autospider.platform.browser.som.text_first import resolve_single_mark_id
from autospider.platform.shared_kernel.types import Action, ActionType

if TYPE_CHECKING:
    from pathlib import Path
    from playwright.async_api import Page
    from autospider.contexts.collection.infrastructure.adapters.llm_navigator import (
        LLMDecisionMaker,
    )


logger = get_logger(__name__)


def _pagination_rule_selectors() -> list[str]:
    """规则兜底只保留语义较强的分页选择器，避免误点泛化按钮。"""
    return [
        'a:has-text("下一页")',
        'button:has-text("下一页")',
        'a:has-text("下页")',
        'button:has-text("下页")',
        'a:has-text("Next")',
        'button:has-text("Next")',
        'a:has-text("next")',
        'button:has-text("next")',
        'a[rel="next"]',
        'a[aria-label*="next" i]',
        'button[aria-label*="next" i]',
        'a[aria-label*="下一页"]',
        'button[aria-label*="下一页"]',
        'a[title*="下一页"]',
        'button[title*="下一页"]',
        'a[title*="next" i]',
        'button[title*="next" i]',
        "#next-page",
        "#nextPage",
        'a[class*="page-next"]:not([class*="disabled"])',
        'button[class*="page-next"]:not([class*="disabled"]):not([disabled])',
        '[class*="pagination"] a[rel="next"]',
        '[class*="pagination"] button[aria-label*="next" i]',
        '[class*="pagination"] a[title*="next" i]',
        '[class*="pagination"] a:has-text("下一页")',
        '[class*="pagination"] button:has-text("下一页")',
    ]


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
        logger.info("[Extract-Pagination] 开始提取分页控件 xpath...")

        # 策略1: 优先使用 LLM 视觉识别（准确度更高）
        if self.llm_decision_maker:
            logger.info("[Extract-Pagination] 策略1: 使用 LLM 视觉识别...")
            result = await self.extract_pagination_xpath_with_llm()
            if result:
                logger.info(f"[Extract-Pagination] ✓ LLM 识别成功: {result}")
                return result
            logger.info("[Extract-Pagination] LLM 识别失败，切换到规则兜底...")

        # 策略2: 规则兜底 - 增强的分页按钮选择器
        logger.info("[Extract-Pagination] 策略2: 使用规则识别...")
        for selector in _pagination_rule_selectors():
            try:
                locator = self.page.locator(selector)
                count = await locator.count()
                if count > 0:
                    # 验证元素是否可见且可点击
                    first_elem = locator.first
                    if await first_elem.is_visible():
                        logger.info(f"[Extract-Pagination] ✓ 规则识别成功: {selector}")
                        self.pagination_xpath = selector
                        return selector
            except Exception:
                continue

        logger.info("[Extract-Pagination] ⚠ 所有策略均失败，未能提取分页控件")
        return None

    async def extract_jump_widget_xpath(self) -> dict[str, str] | None:
        """
        提取页码跳转控件的 xpath（输入框 + 确定按钮）

        用于断点恢复的第二阶段策略（控件直达）

        策略：先用 LLM 视觉识别，失败则使用增强的规则兜底

        Returns:
            {"input": "输入框xpath", "button": "按钮xpath"} 或 None
        """
        logger.info("[Extract-JumpWidget] 开始提取页码跳转控件...")

        # 策略1: 优先使用 LLM 视觉识别（准确度更高）
        if self.llm_decision_maker:
            logger.info("[Extract-JumpWidget] 策略1: 使用 LLM 视觉识别...")
            result = await self._extract_jump_widget_with_llm()
            if result:
                logger.info(f"[Extract-JumpWidget] ✓ LLM 识别成功: {result}")
                self.jump_widget_xpath = result
                return result
            logger.info("[Extract-JumpWidget] LLM 识别失败，切换到规则兜底...")

        # 策略2: 规则兜底
        logger.info("[Extract-JumpWidget] 策略2: 使用规则识别...")
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
                    logger.info(f"[Extract-JumpWidget] ✓ 找到输入框: {selector}")
                    break
            except Exception:
                continue

        if input_xpath:
            for selector in button_selectors:
                try:
                    locator = self.page.locator(selector)
                    if await locator.count() > 0 and await locator.first.is_visible():
                        button_xpath = selector
                        logger.info(f"[Extract-JumpWidget] ✓ 找到按钮: {selector}")
                        break
                except Exception:
                    continue

        if input_xpath and button_xpath:
            self.jump_widget_xpath = {"input": input_xpath, "button": button_xpath}
            logger.info("[Extract-JumpWidget] ✓ 成功提取跳转控件")
            return self.jump_widget_xpath
        else:
            logger.info("[Extract-JumpWidget] ⚠ 未能提取完整的跳转控件")
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

            args = (
                data.get("args")
                if isinstance(data, dict) and isinstance(data.get("args"), dict)
                else {}
            )
            purpose = (args.get("purpose") or "").lower()
            found = coerce_bool(args.get("found"), default=True)

            if (
                data
                and data.get("action") == "select"
                and purpose in {"jump_widget", "page_jump"}
                and found
            ):
                input_obj = args.get("input") if isinstance(args.get("input"), dict) else {}
                button_obj = args.get("button") if isinstance(args.get("button"), dict) else {}
                input_mark_id = input_obj.get("mark_id")
                button_mark_id = button_obj.get("mark_id")
                input_text = input_obj.get("text") or ""
                button_text = button_obj.get("text") or ""

                logger.info(
                    f"[Extract-JumpWidget-LLM] 找到输入框 [{input_mark_id}], 按钮 [{button_mark_id}]"
                )

                input_xpath = None
                button_xpath = None

                try:
                    input_mark_id_value = int(input_mark_id) if input_mark_id is not None else None
                except (TypeError, ValueError):
                    input_mark_id_value = None

                # 文本优先：即使未返回 mark_id，也允许仅凭文本解析输入框元素
                if input_text and (
                    config.url_collector.validate_mark_id or input_mark_id_value is None
                ):
                    corrected_mark_id = await resolve_single_mark_id(
                        page=self.page,
                        llm=self.llm_decision_maker.decider.llm,
                        snapshot=snapshot,
                        mark_id=input_mark_id_value,
                        target_text=input_text,
                        max_retries=config.url_collector.max_validation_retries,
                    )
                    if corrected_mark_id is not None:
                        input_mark_id_value = corrected_mark_id

                element = (
                    next(
                        (m for m in snapshot.marks if m.mark_id == int(input_mark_id_value)),
                        None,
                    )
                    if input_mark_id_value is not None
                    else None
                )
                if element and element.xpath_candidates:
                    sorted_candidates = sorted(element.xpath_candidates, key=lambda x: x.priority)
                    input_xpath = sorted_candidates[0].xpath if sorted_candidates else None

                try:
                    button_mark_id_value = (
                        int(button_mark_id) if button_mark_id is not None else None
                    )
                except (TypeError, ValueError):
                    button_mark_id_value = None

                if button_text and (
                    config.url_collector.validate_mark_id or button_mark_id_value is None
                ):
                    corrected_mark_id = await resolve_single_mark_id(
                        page=self.page,
                        llm=self.llm_decision_maker.decider.llm,
                        snapshot=snapshot,
                        mark_id=button_mark_id_value,
                        target_text=button_text,
                        max_retries=config.url_collector.max_validation_retries,
                    )
                    if corrected_mark_id is not None:
                        button_mark_id_value = corrected_mark_id

                element = (
                    next(
                        (m for m in snapshot.marks if m.mark_id == int(button_mark_id_value)),
                        None,
                    )
                    if button_mark_id_value is not None
                    else None
                )
                if element and element.xpath_candidates:
                    sorted_candidates = sorted(element.xpath_candidates, key=lambda x: x.priority)
                    button_xpath = sorted_candidates[0].xpath if sorted_candidates else None

                if input_xpath and button_xpath:
                    return {"input": input_xpath, "button": button_xpath}
                elif input_xpath:
                    logger.info("[Extract-JumpWidget-LLM] 找到输入框但未找到按钮的 xpath")
                    return None
            else:
                reasoning = data.get("thinking") if isinstance(data, dict) else ""
                logger.info(f"[Extract-JumpWidget-LLM] 未找到跳转控件: {reasoning if data else ''}")
        except Exception as e:
            logger.info(f"[Extract-JumpWidget-LLM] LLM 识别失败: {e}")

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

            args = (
                data.get("args")
                if isinstance(data, dict) and isinstance(data.get("args"), dict)
                else {}
            )
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

            if (
                data
                and data.get("action") == "select"
                and purpose in {"pagination_next", "next_page"}
                and found
                and (mark_id_raw is not None or target_text)
            ):
                reasoning = data.get("thinking") if isinstance(data, dict) else ""
                logger.info(
                    f"[Extract-Pagination-LLM] 找到分页按钮 [{mark_id_raw if mark_id_raw is not None else 'text-only'}]: {reasoning}"
                )

                try:
                    mark_id_value = int(mark_id_raw)
                except (TypeError, ValueError):
                    mark_id_value = None

                # 文本优先：mark_id 可缺省，始终允许按文本纠正/解析
                if target_text and (config.url_collector.validate_mark_id or mark_id_value is None):
                    mark_id_value = await resolve_single_mark_id(
                        page=self.page,
                        llm=self.llm_decision_maker.decider.llm,
                        snapshot=snapshot,
                        mark_id=mark_id_value,
                        target_text=target_text,
                        max_retries=config.url_collector.max_validation_retries,
                    )

                if mark_id_value is None:
                    logger.info("[Extract-Pagination-LLM] 无法根据文本解析分页按钮 mark_id")
                    return None

                # 找到对应的元素，获取其 xpath
                element = next((m for m in snapshot.marks if m.mark_id == mark_id_value), None)
                if element and element.xpath_candidates:
                    # 取优先级最高的 xpath
                    sorted_candidates = sorted(element.xpath_candidates, key=lambda x: x.priority)
                    best_xpath = sorted_candidates[0].xpath if sorted_candidates else None

                    if best_xpath:
                        self.pagination_xpath = best_xpath
                        logger.info(f"[Extract-Pagination-LLM] ✓ 提取到 xpath: {best_xpath}")
                        return best_xpath
            else:
                reasoning = data.get("thinking") if isinstance(data, dict) else ""
                logger.info(f"[Extract-Pagination-LLM] 未找到分页按钮: {reasoning if data else ''}")
        except Exception as e:
            logger.info(f"[Extract-Pagination-LLM] LLM 识别失败: {e}")

        logger.info("[Extract-Pagination] ⚠ 未能提取分页控件 xpath")
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
                    logger.info("[Pagination] 策略1: 使用提取的 xpath...")

                    # 获取随机延迟
                    from autospider.platform.shared_kernel.utils.delay import get_random_delay

                    delay = get_random_delay(
                        config.url_collector.action_delay_base,
                        config.url_collector.action_delay_random,
                    )
                    await asyncio.sleep(delay)

                    await locator.first.click(timeout=5000)
                    await asyncio.sleep(config.url_collector.page_load_delay)

                    self.current_page_num += 1
                    logger.info(f"[Pagination] ✓ 翻页成功，当前第 {self.current_page_num} 页")
                    return True
            except Exception as e:
                logger.info(f"[Pagination] 策略1 失败: {e}")

        # 策略2: 使用 LLM 实时视觉识别
        if self.llm_decision_maker:
            logger.info("[Pagination] 策略2: 使用 LLM 视觉识别...")
            try:
                result = await self.find_next_page_with_llm()
                if result:
                    return True
                logger.info("[Pagination] LLM 识别失败，切换到规则兜底...")
            except Exception as e:
                logger.info(f"[Pagination] 策略2 失败: {e}")

        # 策略3: 增强的规则兜底
        logger.info("[Pagination] 策略3: 使用规则识别...")
        for selector in _pagination_rule_selectors():
            try:
                locator = self.page.locator(selector)
                count = await locator.count()
                if count > 0:
                    first_elem = locator.first
                    # 检查可见性
                    is_visible = await first_elem.is_visible()
                    if is_visible:
                        logger.info(f"[Pagination] 规则匹配: {selector} (共{count}个元素)")

                        from autospider.platform.shared_kernel.utils.delay import get_random_delay

                        delay = get_random_delay(
                            config.url_collector.action_delay_base,
                            config.url_collector.action_delay_random,
                        )
                        await asyncio.sleep(delay)

                        # 尝试点击
                        await first_elem.click(timeout=5000)
                        await asyncio.sleep(config.url_collector.page_load_delay)

                        self.current_page_num += 1
                        logger.info(f"[Pagination] ✓ 翻页成功，当前第 {self.current_page_num} 页")
                        return True
            except Exception as e:
                logger.info(f"[Pagination] 规则 '{selector}' 失败: {e}")
                continue

        logger.info("[Pagination] ⚠ 所有策略均失败，未找到下一页按钮")
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

            args = (
                data.get("args")
                if isinstance(data, dict) and isinstance(data.get("args"), dict)
                else {}
            )
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

            if (
                data
                and data.get("action") == "select"
                and purpose in {"pagination_next", "next_page"}
                and found
                and (mark_id_raw is not None or target_text)
            ):
                logger.info(
                    f"[Pagination-LLM] 找到下一页按钮 [{mark_id_raw if mark_id_raw is not None else 'text-only'}]"
                )

                try:
                    mark_id_value = int(mark_id_raw)
                except (TypeError, ValueError):
                    mark_id_value = None

                if target_text and (config.url_collector.validate_mark_id or mark_id_value is None):
                    mark_id_value = await resolve_single_mark_id(
                        page=self.page,
                        llm=self.llm_decision_maker.decider.llm,
                        snapshot=snapshot,
                        mark_id=mark_id_value,
                        target_text=target_text,
                        max_retries=config.url_collector.max_validation_retries,
                    )

                mark_id_to_xpath = build_mark_id_to_xpath_map(snapshot)
                executor = ActionExecutor(self.page)

                logger.info(f"[Pagination-LLM] 尝试点击 mark_id={mark_id_value}...")
                from autospider.platform.shared_kernel.utils.delay import get_random_delay

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
                    logger.info("[Pagination-LLM] Unexpected new tab opened; treat as failure.")
                    return False

                if not result.success:
                    logger.info(f"[Pagination-LLM] 点击失败: {result.error}")
                    return False

                await asyncio.sleep(config.url_collector.page_load_delay)
                self.current_page_num += 1
                logger.info(f"[Pagination-LLM] ✓ 翻页成功，当前第 {self.current_page_num} 页")
                return True
            else:
                reasoning = data.get("thinking") if isinstance(data, dict) else ""
                logger.info(f"[Pagination-LLM] 未找到下一页: {reasoning if data else ''}")
        except Exception as e:
            logger.info(f"[Pagination-LLM] LLM 识别失败: {e}")

        return False
