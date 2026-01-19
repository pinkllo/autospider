"""动作执行器"""

from __future__ import annotations

# NOTE: Deprecated legacy copy. Prefer:
#   autospider.common.browser.actions.ActionExecutor

import asyncio
from typing import TYPE_CHECKING

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from ..types import Action, ActionResult, ActionType, ScriptStep, ScriptStepType

if TYPE_CHECKING:
    from ..types import SoMSnapshot


class ActionExecutor:
    """动作执行器"""

    def __init__(self, page: Page):
        self.page = page

    async def execute(
        self,
        action: Action,
        mark_id_to_xpath: dict[int, list[str]],
        step_index: int,
    ) -> tuple[ActionResult, ScriptStep | None]:
        """
        执行动作
        
        返回: (执行结果, 脚本步骤 - 用于沉淀)
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
            elif action.action == ActionType.GUARD:
                return await self._execute_guard()
            elif action.action == ActionType.GO_BACK:
                return await self._execute_go_back(action, step_index)
            elif action.action == ActionType.DONE:
                return ActionResult(success=True), None
            elif action.action == ActionType.RETRY:
                return ActionResult(success=True), None
            else:
                return ActionResult(success=False, error=f"Unknown action: {action.action}"), None
        except PlaywrightTimeout as e:
            return ActionResult(success=False, error=f"Timeout: {str(e)}"), None
        except Exception as e:
            return ActionResult(success=False, error=str(e)), None

    async def _find_element_by_xpath_list(self, xpaths: list[str]):
        """
        按优先级尝试多个 XPath，返回第一个匹配的元素
        
        实现你建议的 Priority Fallback 策略
        """
        for xpath in xpaths:
            try:
                locator = self.page.locator(f"xpath={xpath}")
                count = await locator.count()
                if count == 1:
                    # 确保元素可见
                    if await locator.is_visible():
                        return locator, xpath
            except Exception:
                continue
        return None, None

    async def _execute_click(
        self,
        action: Action,
        mark_id_to_xpath: dict[int, list[str]],
        step_index: int,
    ) -> tuple[ActionResult, ScriptStep | None]:
        """执行点击动作"""
        if action.mark_id is None:
            return ActionResult(success=False, error="click requires mark_id"), None

        xpaths = mark_id_to_xpath.get(action.mark_id, [])
        if not xpaths:
            return ActionResult(success=False, error=f"mark_id {action.mark_id} not found"), None

        # 尝试找到元素
        locator, used_xpath = await self._find_element_by_xpath_list(xpaths)
        if not locator:
            # 退回使用 data-som-id
            locator = self.page.locator(f'[data-som-id="{action.mark_id}"]')
            used_xpath = f'//*[@data-som-id="{action.mark_id}"]'
            if await locator.count() == 0:
                return ActionResult(success=False, error=f"Element not found for mark_id {action.mark_id}"), None

        # 记录当前页面数量
        context = self.page.context
        pages_before = len(context.pages)
        
        # 使用 expect_page 监听新页面（无论是 target="_blank" 还是 JS window.open）
        try:
            async with context.expect_page(timeout=3000) as new_page_info:
                await locator.click(timeout=action.timeout_ms)
            
            # 有新页面打开
            new_page = await new_page_info.value
            await new_page.wait_for_load_state("domcontentloaded")
            print(f"[Click] 检测到新标签页打开: {new_page.url}")
            self._new_page = new_page
            
        except Exception:
            # 没有新页面打开，普通点击
            pass

        # 等待页面响应
        await asyncio.sleep(0.5)

        # 生成脚本步骤
        script_step = ScriptStep(
            step=step_index,
            action=ScriptStepType.CLICK,
            target_xpath=used_xpath,
            xpath_alternatives=xpaths[:5],  # 保留前 5 个候选
            description=action.thinking or f"点击元素 [{action.mark_id}]",
        )

        return ActionResult(success=True, new_url=self.page.url), script_step

    async def _execute_type(
        self,
        action: Action,
        mark_id_to_xpath: dict[int, list[str]],
        step_index: int,
    ) -> tuple[ActionResult, ScriptStep | None]:
        """执行输入动作"""
        if action.mark_id is None:
            return ActionResult(success=False, error="type requires mark_id"), None
        if not action.text:
            return ActionResult(success=False, error="type requires text"), None

        xpaths = mark_id_to_xpath.get(action.mark_id, [])
        if not xpaths:
            return ActionResult(success=False, error=f"mark_id {action.mark_id} not found"), None

        locator, used_xpath = await self._find_element_by_xpath_list(xpaths)
        if not locator:
            locator = self.page.locator(f'[data-som-id="{action.mark_id}"]')
            used_xpath = f'//*[@data-som-id="{action.mark_id}"]'

        # 先清空再输入
        await locator.click()
        await locator.fill(action.text, timeout=action.timeout_ms)

        # 生成脚本步骤（使用占位符语法）
        # 检测是否应该参数化
        value = action.text
        if len(value) > 0:  # 较长的输入可能需要参数化
            # 这里可以添加更智能的参数化逻辑
            pass

        script_step = ScriptStep(
            step=step_index,
            action=ScriptStepType.TYPE,
            target_xpath=used_xpath,
            xpath_alternatives=xpaths[:5],
            value=value,
            description=action.thinking or f"在元素 [{action.mark_id}] 输入文本",
        )

        return ActionResult(success=True), script_step

    async def _execute_press(
        self,
        action: Action,
        mark_id_to_xpath: dict[int, list[str]],
        step_index: int,
    ) -> tuple[ActionResult, ScriptStep | None]:
        """执行按键动作"""
        key = action.key or "Enter"

        if action.mark_id is not None:
            xpaths = mark_id_to_xpath.get(action.mark_id, [])
            locator, used_xpath = await self._find_element_by_xpath_list(xpaths)
            if locator:
                await locator.press(key)
            else:
                await self.page.keyboard.press(key)
                used_xpath = None
        else:
            await self.page.keyboard.press(key)
            used_xpath = None

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
        """执行滚动动作"""
        delta = action.scroll_delta or (0, 300)  # 默认向下滚动 300px

        await self.page.mouse.wheel(delta[0], delta[1])
        await asyncio.sleep(0.3)

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
        """执行导航动作"""
        if not action.url:
            return ActionResult(success=False, error="navigate requires url"), None

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
        """执行等待动作"""
        timeout_ms = action.timeout_ms or 2000
        
        try:
            await self.page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except PlaywrightTimeout:
            pass  # 超时不算失败

        script_step = ScriptStep(
            step=step_index,
            action=ScriptStepType.WAIT,
            timeout_ms=timeout_ms,
            wait_condition="networkidle",
            description=action.thinking or f"等待页面加载 ({timeout_ms}ms)",
        )

        return ActionResult(success=True), script_step

    async def _execute_guard(self) -> tuple[ActionResult, ScriptStep | None]:
        """Force trigger login takeover when the model detects login/anti-bot UI."""
        try:
            import browser_manager.handlers as _handlers  # noqa: F401
            from browser_manager.guard import PageGuard
            from browser_manager.registry import get_registry
            from browser_manager.handlers.login_handler import LoginHandler
        except Exception as e:
            return ActionResult(success=False, error=f"Guard import failed: {e}"), None

        # Ensure a guard is attached for future navigations
        guard = getattr(self.page, "_page_guard", None)
        if guard is None:
            guard = PageGuard()
            guard.attach_to_page(self.page)
            setattr(self.page, "_guard_attached", True)
            setattr(self.page, "_page_guard", guard)

        # Force run the login handler regardless of detect() outcome
        try:
            registry = get_registry()
            handler = registry.get_all_handlers().get("人工登录接管")
            if handler is None:
                handler = LoginHandler(auth_file=None)
                registry.register(handler)
            await handler.handle(self.page)
            return ActionResult(success=True), None
        except Exception as e:
            return ActionResult(success=False, error=str(e)), None

    async def _execute_extract(
        self,
        action: Action,
        mark_id_to_xpath: dict[int, list[str]],
        step_index: int,
    ) -> tuple[ActionResult, ScriptStep | None]:
        """执行提取动作"""
        extracted_text = None
        used_xpath = None

        if action.mark_id is not None:
            xpaths = mark_id_to_xpath.get(action.mark_id, [])
            locator, used_xpath = await self._find_element_by_xpath_list(xpaths)
            if locator:
                element_text = await locator.inner_text()
                
                # 智能提取：如果是表格标题（th），尝试获取同行的值（td）
                tag_name = await locator.evaluate("el => el.tagName.toLowerCase()")
                if tag_name == "th":
                    # 获取父 tr 元素
                    parent_tr = locator.locator("xpath=..")
                    # 尝试获取下一个兄弟 td
                    try:
                        next_td = parent_tr.locator("td").first
                        if await next_td.count() > 0:
                            extracted_text = await next_td.inner_text()
                            # 更新 xpath 指向 td
                            if used_xpath:
                                # 将 /th 替换为 /td 或 /following-sibling::td[1]
                                used_xpath = used_xpath.replace("/th", "/following-sibling::td[1]")
                        else:
                            extracted_text = element_text
                    except Exception:
                        extracted_text = element_text
                else:
                    extracted_text = element_text
            else:
                # 尝试用 data-som-id
                locator = self.page.locator(f'[data-som-id="{action.mark_id}"]')
                if await locator.count() > 0:
                    extracted_text = await locator.inner_text()
                    used_xpath = f'//*[@data-som-id="{action.mark_id}"]'

        # 如果没有指定 mark_id，尝试从页面提取目标文本
        if extracted_text is None and action.target_text:
            # 搜索包含目标文本的元素
            locator = self.page.locator(f"text={action.target_text}").first
            if await locator.count() > 0:
                extracted_text = await locator.inner_text()

        script_step = ScriptStep(
            step=step_index,
            action=ScriptStepType.EXTRACT,
            target_xpath=used_xpath,
            description=action.thinking or f"提取文本",
        )

        return ActionResult(success=True, extracted_text=extracted_text), script_step

    async def _execute_go_back(
        self,
        action: Action,
        step_index: int,
    ) -> tuple[ActionResult, ScriptStep | None]:
        """执行返回上一页动作"""
        try:
            await self.page.go_back(wait_until="domcontentloaded", timeout=action.timeout_ms)
            await asyncio.sleep(0.5)  # 等待页面稳定
            
            # go_back 不需要沉淀到脚本中（一般是用户导航的临时操作）
            return ActionResult(success=True, new_url=self.page.url), None
        except Exception as e:
            return ActionResult(success=False, error=f"无法返回: {str(e)}"), None
