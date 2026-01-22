"""URL 提取模块 - 负责从元素中提取 URL"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlparse

from ...common.browser.actions import ActionExecutor
from ...common.browser.click_utils import click_and_capture_new_page
from ...common.som import build_mark_id_to_xpath_map, set_overlay_visibility
from ...common.types import Action, ActionType

if TYPE_CHECKING:
    from playwright.async_api import Page
    from ...common.types import ElementMark, SoMSnapshot


class URLExtractor:
    """URL 提取器，负责从页面元素中提取详情页 URL。

    该类通过两种策略提取 URL：
    1. 静态提取：直接获取元素的 href 属性（最快）。
    2. 动态提取：模拟点击元素，并捕获产生的新页面 URL 或当前页面跳转后的 URL（最准确，用于处理 JS 跳转）。
    """

    def __init__(self, page: "Page", list_url: str):
        """
        初始化 URL 提取器。

        Args:
            page: Playwright 页面对象。
            list_url: 列表页的原始 URL，用于处理相对路径和回退导航。
        """
        self.page = page
        self.list_url = list_url

    async def extract_from_element(
        self,
        element: "ElementMark",
        snapshot: "SoMSnapshot",
        nav_steps: list[dict] | None = None,
    ) -> str | None:
        """
        从元素中提取 URL。

        优先尝试从元素的 href 属性中提取。如果元素没有 href 属性，
        则尝试通过点击该元素并观察页面跳转来获取 URL。

        Args:
            element: SoM 标记的元素对象。
            snapshot: 当前页面的 SoM 快照，包含元素映射关系。
            nav_steps: 到达当前页面所需的导航步骤（可选），用于点击后回退失败时的恢复。

        Returns:
            提取到的绝对 URL，如果提取失败则返回 None。
        """
        # 策略 1: 优先尝试从 href 属性提取（静态提取）
        if element.href:
            # 使用 urljoin 处理相对路径
            url = urljoin(self.list_url, element.href)
            print(f"[Extract] ✓ 从 href 提取: {url[:60]}...")
            return url

        # 策略 2: 元素无 href，尝试点击获取（动态提取）
        print("[Extract] 元素无 href，点击获取 URL...")
        return await self.click_and_get_url(element, snapshot, nav_steps=nav_steps)

    async def click_and_get_url(
        self,
        element: "ElementMark",
        snapshot: "SoMSnapshot",
        nav_steps: list[dict] | None = None,
    ) -> str | None:
        """
        点击元素并捕获新生成的 URL。

        该方法处理两种情况：
        1. 点击后打开了新标签页：获取新标签页的 URL 并关闭它。
        2. 点击后在当前标签页跳转：获取新 URL 后尝试导航回原始列表页。

        Args:
            element: 目标元素对象。
            snapshot: 用于查找元素 XPath 的快照。
            nav_steps: 用于回退恢复的导航步骤。

        Returns:
            点击后产生的 URL，失败返回 None。
        """
        list_url = self.page.url
        print(f"[Click] 当前 URL: {list_url[:60]}...")

        try:
            # 在执行点击动作前隐藏 SoM 遮罩，避免干扰点击
            await set_overlay_visibility(self.page, False)

            # 构建 mark_id 到 XPath 的映射，以便执行器能找到元素
            mark_id_to_xpath = build_mark_id_to_xpath_map(snapshot)
            executor = ActionExecutor(self.page)

            # 执行点击动作，设置 5 秒超时
            result, _ = await executor.execute(
                Action(action=ActionType.CLICK, mark_id=element.mark_id, timeout_ms=5000),
                mark_id_to_xpath,
                step_index=0,
            )

            if not result.success:
                print(f"[Click] ✗ 点击失败: {result.error}")
                return None

            # 检查是否产生了新页面（ActionExecutor 会自动捕获新页面）
            new_page = getattr(executor, "_new_page", None)
            if new_page is not None:
                new_url = new_page.url
                print(f"[Click] ✓ 检测到新标签页: {new_url[:60]}...")
                try:
                    await new_page.close()
                except Exception:
                    pass
                # 清理执行器状态
                executor._new_page = None
                return new_url

            # 处理当前页面跳转的情况
            # 等待一小段时间让跳转发生
            await asyncio.sleep(2)
            new_url = self.page.url

            # 解析 URL 以比较是否发生实质性变化（包括 hash 变化）
            old_parsed = urlparse(list_url)
            new_parsed = urlparse(new_url)

            print(f"[Click] 旧 URL: {list_url}")
            print(f"[Click] 新 URL: {new_url}")

            if new_url != list_url or old_parsed.fragment != new_parsed.fragment:
                print("[Click] ✓ URL 已变化")
                print("[Click] 返回列表页...")

                # 如果发生了跳转，需要导航回列表页以继续后续提取
                await self.page.goto(self.list_url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(1)

                # 如果有导航步骤（如点击了某些筛选条件），需要重放以恢复到之前的状态
                if nav_steps:
                    from .navigation_handler import NavigationHandler

                    nav_handler = NavigationHandler(self.page, self.list_url, "", 10)
                    await nav_handler.replay_nav_steps(nav_steps)

                return new_url

            # 如果 URL 没有任何变化，说明该点击可能未触发导航
            print("[Click] ✗ URL 未变化")
            try:
                # 尝试回退
                await self.page.go_back(wait_until="domcontentloaded", timeout=5000)
                await asyncio.sleep(1)
            except Exception:
                # 回退失败则尝试重新进入列表页
                try:
                    await self.page.goto(
                        self.list_url, wait_until="domcontentloaded", timeout=30000
                    )
                    await asyncio.sleep(1)
                    if nav_steps:
                        from .navigation_handler import NavigationHandler

                        nav_handler = NavigationHandler(self.page, self.list_url, "", 10)
                        await nav_handler.replay_nav_steps(nav_steps)
                except Exception:
                    pass

            return None
        except Exception as e:
            print(f"[Click] ✗ 点击失败: {e}")
            # 异常情况下尝试恢复环境
            try:
                await self.page.goto(self.list_url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(1)
                if nav_steps:
                    from .navigation_handler import NavigationHandler

                    nav_handler = NavigationHandler(self.page, self.list_url, "", 10)
                    await nav_handler.replay_nav_steps(nav_steps)
            except Exception:
                pass
            return None

    async def click_element_and_get_url(
        self, element_locator, nav_steps: list[dict] = None
    ) -> str | None:
        """
        通过 Playwright Locator 点击元素并获取 URL。

        该方法主要用于收集阶段，当已经定位到具体的 Playwright 元素时使用。
        逻辑与 click_and_get_url 类似，但使用 click_and_capture_new_page 工具函数。

        Args:
            element_locator: Playwright 的 Locator 对象。
            nav_steps: 导航恢复步骤。

        Returns:
            获取到的 URL 或 None。
        """
        from .navigation_handler import NavigationHandler

        list_url = self.page.url

        try:
            # 使用工具函数点击并捕获新页面
            new_page = await click_and_capture_new_page(
                page=self.page,
                locator=element_locator,
                click_timeout_ms=5000,
                expect_page_timeout_ms=3000,
                load_state="domcontentloaded",
                load_timeout_ms=10000,
            )

            if new_page is not None:
                new_url = new_page.url
                await new_page.close()
                return new_url

            # 检查当前页面是否发生跳转
            await asyncio.sleep(2)
            new_url = self.page.url

            old_parsed = urlparse(list_url)
            new_parsed = urlparse(new_url)

            if new_url != list_url or old_parsed.fragment != new_parsed.fragment:
                # URL 已变化，返回列表页并恢复状态
                await self.page.goto(self.list_url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(1)

                if nav_steps:
                    nav_handler = NavigationHandler(self.page, self.list_url, "", 10)
                    await nav_handler.replay_nav_steps(nav_steps)

                return new_url

            # 未发生跳转，尝试回退
            try:
                await self.page.go_back(wait_until="domcontentloaded", timeout=5000)
                await asyncio.sleep(1)
            except Exception:
                try:
                    await self.page.goto(
                        self.list_url,
                        wait_until="domcontentloaded",
                        timeout=30000,
                    )
                    await asyncio.sleep(1)
                    if nav_steps:
                        nav_handler = NavigationHandler(self.page, self.list_url, "", 10)
                        await nav_handler.replay_nav_steps(nav_steps)
                except Exception:
                    pass

            return None

        except Exception as e:
            print(f"[Collect-XPath] 点击失败: {e}")
            # 异常恢复
            try:
                await self.page.goto(self.list_url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(1)
                if nav_steps:
                    nav_handler = NavigationHandler(self.page, self.list_url, "", 10)
                    await nav_handler.replay_nav_steps(nav_steps)
            except Exception:
                pass
            return None
