"""动作执行器"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from playwright.async_api import TimeoutError as PlaywrightTimeout

from ..types import Action, ActionResult, ActionType, ScriptStep, ScriptStepType
from .click_utils import click_and_capture_new_page

if TYPE_CHECKING:
    from browser_manager.guarded_page import GuardedPage


class ActionExecutor:
    """
    动作执行器类，负责将抽象的 Action 转换为具体的 Playwright 浏览器操作。
    支持点击、输入、滚动、导航、提取等多种动作，并能够自动处理新标签页切换。
    同时负责将执行过程沉淀为 ScriptStep，用于后续生成自动化脚本。
    """

    def __init__(self, page: "GuardedPage"):
        """
        初始化动作执行器。

        Args:
            page: GuardedPage 对象，已包装的页面代理。
        """
        self.page = page

    async def execute(
        self,
        action: Action,
        mark_id_to_xpath: dict[int, list[str]],
        step_index: int,
    ) -> tuple[ActionResult, ScriptStep | None]:
        """
        根据动作类型分发并执行具体的浏览器操作。

        Args:
            action: 要执行的动作定义。
            mark_id_to_xpath: 元素 mark_id 到 XPath 候选列表的映射表。
            step_index: 当前动作在任务流中的序号。

        Returns:
            tuple[ActionResult, ScriptStep | None]:
                - ActionResult: 包含执行是否成功、错误信息、新页面 URL、提取的文本等。
                - ScriptStep: 沉淀后的脚本步骤，如果动作为 DONE/RETRY/GO_BACK 等则可能为 None。
        """
        try:
            if action.action == ActionType.CLICK:
                return await self._execute_click(action, mark_id_to_xpath, step_index)
            elif action.action == ActionType.TYPE:
                return await self._execute_type(action, mark_id_to_xpath, step_index)
            elif action.action == ActionType.PRESS:
                return await self._execute_press(action, mark_id_to_xpath, step_index)
            elif action.action == ActionType.SCROLL:
                return await self._execute_scroll(action, step_index)
            elif action.action == ActionType.NAVIGATE:
                return await self._execute_navigate(action, step_index)
            elif action.action == ActionType.WAIT:
                return await self._execute_wait(action, step_index)
            elif action.action == ActionType.EXTRACT:
                return await self._execute_extract(action, mark_id_to_xpath, step_index)
            elif action.action == ActionType.GO_BACK:
                return await self._execute_go_back(action, step_index)
            elif action.action == ActionType.GO_BACK_TAB:
                return await self._execute_go_back_tab(step_index)
            elif action.action == ActionType.DONE:
                return ActionResult(success=True), None
            elif action.action == ActionType.RETRY:
                return ActionResult(success=True), None
            else:
                return ActionResult(success=False, error=f"未知动作类型: {action.action}"), None
        except PlaywrightTimeout as e:
            return ActionResult(success=False, error=f"操作超时: {str(e)}"), None
        except Exception as e:
            return ActionResult(success=False, error=f"执行异常: {str(e)}"), None

    async def _find_element_by_xpath_list(self, xpaths: list[str]):
        """
        实现 Priority Fallback 策略：按优先级尝试多个 XPath，返回第一个匹配且可见的元素。

        Args:
            xpaths: XPath 字符串列表，按优先级排序。

        Returns:
            tuple[Locator | None, str | None]: 匹配到的 Playwright Locator 和对应的 XPath。
        """
        for xpath in xpaths:
            try:
                locator = self.page.locator(f"xpath={xpath}")
                count = await locator.count()
                if count == 1:
                    # 只有当元素可见时才认为匹配成功，避免操作隐藏元素
                    if await locator.is_visible():
                        return locator, xpath
            except Exception:
                continue
        return None, None

    def _is_page_closed(self, page: "GuardedPage") -> bool:
        """
        判断 GuardedPage 是否已关闭。
        """
        try:
            return bool(page.unwrap().is_closed())
        except Exception:
            return False

    async def _execute_click(
        self,
        action: Action,
        mark_id_to_xpath: dict[int, list[str]],
        step_index: int,
    ) -> tuple[ActionResult, ScriptStep | None]:
        """
        执行点击动作。
        包含：元素定位、新标签页捕获、自动页面切换。
        """
        if action.mark_id is None:
            return ActionResult(success=False, error="点击动作缺少 mark_id"), None

        xpaths = mark_id_to_xpath.get(action.mark_id, [])
        if not xpaths:
            return (
                ActionResult(success=False, error=f"未找到 mark_id {action.mark_id} 对应的 XPath"),
                None,
            )

        # 1. 尝试使用提供的 XPath 候选列表定位元素
        locator, used_xpath = await self._find_element_by_xpath_list(xpaths)

        if not locator:
            # 2. 如果候选列表失效，回退使用 data-som-id 属性定位
            locator = self.page.locator(f'[data-som-id="{action.mark_id}"]')
            used_xpath = f'//*[@data-som-id="{action.mark_id}"]'
            if await locator.count() == 0:
                return (
                    ActionResult(success=False, error=f"无法定位元素 (mark_id: {action.mark_id})"),
                    None,
                )

        # 3. 执行点击并尝试捕获可能产生的新标签页
        new_page = await click_and_capture_new_page(
            page=self.page,
            locator=locator,
            click_timeout_ms=action.timeout_ms,
            expect_page_timeout_ms=3000,
            load_state="domcontentloaded",
            load_timeout_ms=10000,
        )

        if new_page is not None:
            print(f"[Click] 检测到新标签页: {new_page.url}")
            # 立即切换当前执行器的页面引用，确保后续动作在正确的页面上执行
            self._previous_page = self.page
            self.page = new_page
            self._new_page = new_page  # 保留引用供外部管理器感知

        # 等待页面响应，确保状态稳定
        await asyncio.sleep(0.5)

        # 4. 生成脚本步骤，用于沉淀
        script_step = ScriptStep(
            step=step_index,
            action=ScriptStepType.CLICK,
            target_xpath=used_xpath,
            xpath_alternatives=xpaths[:5],  # 保留前 5 个候选 XPath 增强鲁棒性
            description=action.thinking or f"点击元素 [{action.mark_id}]",
        )

        return ActionResult(success=True, new_url=self.page.url), script_step

    async def _execute_type(
        self,
        action: Action,
        mark_id_to_xpath: dict[int, list[str]],
        step_index: int,
    ) -> tuple[ActionResult, ScriptStep | None]:
        """
        执行输入文本动作。
        支持：清空输入框、输入文本、模拟回车等按键。
        """
        if action.mark_id is None:
            return ActionResult(success=False, error="输入动作缺少 mark_id"), None
        if not action.text:
            return ActionResult(success=False, error="输入动作缺少文本内容"), None

        xpaths = mark_id_to_xpath.get(action.mark_id, [])
        locator, used_xpath = await self._find_element_by_xpath_list(xpaths)
        if not locator:
            locator = self.page.locator(f'[data-som-id="{action.mark_id}"]')
            used_xpath = f'//*[@data-som-id="{action.mark_id}"]'

        # 1. 聚焦并填充内容
        await locator.click()
        await locator.fill(action.text, timeout=action.timeout_ms)

        # 2. 处理后续按键（如回车搜索）
        pressed_key = action.key
        if not pressed_key:
            # 智能推断：如果是搜索框，通常需要按回车
            target_hint = f"{action.target_text or ''} {action.expectation or ''}"
            if "搜索" in target_hint or "search" in target_hint.lower():
                pressed_key = "Enter"

        if pressed_key:
            try:
                await locator.press(pressed_key, timeout=action.timeout_ms)
            except Exception:
                # 如果元素无法直接接收按键，尝试使用全局键盘模拟
                try:
                    await self.page.keyboard.press(pressed_key)
                except Exception:
                    pass

        # 3. 生成脚本步骤
        value = action.text
        script_step = ScriptStep(
            step=step_index,
            action=ScriptStepType.TYPE,
            target_xpath=used_xpath,
            xpath_alternatives=xpaths[:5],
            value=value,
            key=pressed_key,
            description=action.thinking or f"在元素 [{action.mark_id}] 输入文本",
        )

        return ActionResult(success=True), script_step

    async def _execute_press(
        self,
        action: Action,
        mark_id_to_xpath: dict[int, list[str]],
        step_index: int,
    ) -> tuple[ActionResult, ScriptStep | None]:
        """
        执行纯按键动作（如 Enter, Escape, ArrowDown 等）。
        """
        key = action.key or "Enter"

        locator = None
        used_xpath = None
        if action.mark_id is not None:
            xpaths = mark_id_to_xpath.get(action.mark_id, [])
            locator, used_xpath = await self._find_element_by_xpath_list(xpaths)

        # 优先在特定元素上按键，否则在页面上全局按键
        if locator:
            await locator.press(key)
        else:
            await self.page.keyboard.press(key)

        script_step = ScriptStep(
            step=step_index,
            action=ScriptStepType.PRESS,
            target_xpath=used_xpath,
            key=key,
            description=action.thinking or f"按键 {key}",
        )

        return ActionResult(success=True), script_step

    async def _execute_scroll(
        self,
        action: Action,
        step_index: int,
    ) -> tuple[ActionResult, ScriptStep | None]:
        """
        执行页面滚动。
        """
        delta = action.scroll_delta or (0, 300)  # 默认垂直向下滚动 300 像素

        await self.page.mouse.wheel(delta[0], delta[1])
        await asyncio.sleep(0.3)  # 等待滚动动画完成

        script_step = ScriptStep(
            step=step_index,
            action=ScriptStepType.SCROLL,
            scroll_delta=delta,
            description=action.thinking or f"滚动页面 ({delta[0]}, {delta[1]})",
        )

        return ActionResult(success=True), script_step

    async def _execute_navigate(
        self,
        action: Action,
        step_index: int,
    ) -> tuple[ActionResult, ScriptStep | None]:
        """
        执行页面跳转。
        """
        if not action.url:
            return ActionResult(success=False, error="导航动作缺少 URL"), None

        await self.page.goto(action.url, wait_until="domcontentloaded", timeout=action.timeout_ms)

        script_step = ScriptStep(
            step=step_index,
            action=ScriptStepType.NAVIGATE,
            url=action.url,
            description=action.thinking or f"导航到 {action.url}",
        )

        return ActionResult(success=True, new_url=self.page.url), script_step

    async def _execute_wait(
        self,
        action: Action,
        step_index: int,
    ) -> tuple[ActionResult, ScriptStep | None]:
        """
        显式等待动作。
        """
        timeout_ms = action.timeout_ms or 2000

        try:
            # 默认等待网络空闲
            await self.page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except PlaywrightTimeout:
            # 等待超时不视作执行失败
            pass

        script_step = ScriptStep(
            step=step_index,
            action=ScriptStepType.WAIT,
            timeout_ms=timeout_ms,
            wait_condition="networkidle",
            description=action.thinking or f"等待页面加载 ({timeout_ms}ms)",
        )

        return ActionResult(success=True), script_step

    async def _execute_extract(
        self,
        action: Action,
        mark_id_to_xpath: dict[int, list[str]],
        step_index: int,
    ) -> tuple[ActionResult, ScriptStep | None]:
        """
        执行文本提取动作。
        支持：指定元素提取、表格智能提取（th -> td）、根据目标文本模糊定位提取。
        """
        extracted_text = None
        used_xpath = None

        if action.mark_id is not None:
            xpaths = mark_id_to_xpath.get(action.mark_id, [])
            locator, used_xpath = await self._find_element_by_xpath_list(xpaths)
            if locator:
                element_text = await locator.inner_text()

                # 1. 智能提取逻辑：
                # 如果 LLM 指定提取的是表头（th），用户通常其实想要的是该表头对应的值（td）
                tag_name = await locator.evaluate("el => el.tagName.toLowerCase()")
                if tag_name == "th":
                    parent_tr = locator.locator("xpath=..")
                    try:
                        # 尝试获取同一行中的第一个 td
                        next_td = parent_tr.locator("td").first
                        if await next_td.count() > 0:
                            extracted_text = await next_td.inner_text()
                            # 调整脚本中的 XPath，使其指向实际的数据节点
                            if used_xpath:
                                used_xpath = used_xpath.replace("/th", "/following-sibling::td[1]")
                        else:
                            extracted_text = element_text
                    except Exception:
                        extracted_text = element_text
                else:
                    extracted_text = element_text
            else:
                # 回退方案：data-som-id
                locator = self.page.locator(f'[data-som-id="{action.mark_id}"]')
                if await locator.count() > 0:
                    extracted_text = await locator.inner_text()
                    used_xpath = f'//*[@data-som-id="{action.mark_id}"]'

        # 2. 如果 mark_id 提取失败，尝试根据目标文本内容直接查找
        if extracted_text is None and action.target_text:
            locator = self.page.locator(f"text={action.target_text}").first
            if await locator.count() > 0:
                extracted_text = await locator.inner_text()

        script_step = ScriptStep(
            step=step_index,
            action=ScriptStepType.EXTRACT,
            target_xpath=used_xpath,
            description=action.thinking or "提取文本内容",
        )

        return ActionResult(success=True, extracted_text=extracted_text), script_step

    async def _execute_go_back(
        self,
        action: Action,
        step_index: int,
    ) -> tuple[ActionResult, ScriptStep | None]:
        """
        执行浏览器返回上一页动作。
        """
        try:
            await self.page.go_back(wait_until="domcontentloaded", timeout=action.timeout_ms)
            await asyncio.sleep(0.5)

            # 通常返回操作不需要沉淀为固定的脚本步骤
            return ActionResult(success=True, new_url=self.page.url), None
        except Exception as e:
            return ActionResult(success=False, error=f"无法返回上一页: {str(e)}"), None

    async def _execute_go_back_tab(
        self,
        step_index: int,
    ) -> tuple[ActionResult, ScriptStep | None]:
        """
        关闭当前标签页并返回到上一个（父）标签页。
        常用于处理点击后产生的新窗口。
        """
        try:
            current_page = self.page
            raw_current = current_page.unwrap()

            # 1. 寻找目标返回页面
            # 优先寻找 window.opener
            opener = None
            try:
                opener = getattr(raw_current, "opener", None)
                if callable(opener):
                    opener = opener()
            except Exception:
                opener = None

            # 其次寻找执行器记录的 previous_page
            target_page = opener or getattr(self, "_previous_page", None)

            # 最后在 context 中寻找最后一个非当前的页面（使用 GuardedContext）
            if target_page is None:
                try:
                    # 通过 GuardedPage.context.pages 获取 GuardedPage 列表
                    pages = current_page.context.pages
                    for candidate in reversed(pages):
                        # GuardedPage 比较：解包后比较原始页面
                        if candidate.unwrap() is raw_current:
                            continue
                        target_page = candidate
                        break
                except Exception:
                    target_page = None

            if target_page is None:
                return ActionResult(success=False, error="无法找到可切回的标签页"), None

            # 2. 关闭当前页
            try:
                # 对于 GuardedPage，比较时需要解包
                target_raw = target_page.unwrap() if hasattr(target_page, "unwrap") else target_page
                if raw_current is not target_raw and not self._is_page_closed(current_page):
                    await current_page.close()
            except Exception:
                pass

            # 3. 切换到目标页（已经是 GuardedPage）
            self.page = target_page
            self._new_page = target_page
            return ActionResult(success=True, new_url=self.page.url), None
        except Exception as e:
            return ActionResult(success=False, error=f"切回标签页失败: {str(e)}"), None
