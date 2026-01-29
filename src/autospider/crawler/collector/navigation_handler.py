"""导航处理模块 - 负责导航阶段和步骤重放"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from ...common.browser import ActionExecutor
from ...common.browser.click_utils import click_and_capture_new_page
from ...common.som import (
    clear_overlay,
    inject_and_scan,
    capture_screenshot_with_marks,
    build_mark_id_to_xpath_map,
    format_marks_for_llm,
    set_overlay_visibility,
)
from ...common.types import AgentState, RunInput, ActionType

if TYPE_CHECKING:
    from pathlib import Path
    from playwright.async_api import Page
    from ...common.llm import LLMDecider


class NavigationHandler:
    """导航处理器，负责导航阶段的筛选操作和步骤重放"""

    def __init__(
        self,
        page: "Page",
        list_url: str,
        task_description: str,
        max_nav_steps: int,
        decider: "LLMDecider" = None,
        screenshots_dir: "Path" = None,
    ):
        self.page = page
        self.list_url = list_url
        self.task_description = task_description
        self.max_nav_steps = max_nav_steps
        self.decider = decider
        self.screenshots_dir = screenshots_dir
        self.executor: ActionExecutor | None = None
        self.nav_steps: list[dict] = []

    async def run_navigation_phase(self) -> bool:
        """
        导航阶段：让 LLM 根据任务描述进行筛选操作

        Returns:
            是否成功完成导航
        """
        if not self.decider:
            return False

        # 初始化执行器
        if not self.executor:
            self.executor = ActionExecutor(self.page)

        # 设置决策器的任务计划
        self.decider.task_plan = f"""任务分析: 你需要先在列表页进行筛选操作，达到以下目标：
{self.task_description}

执行步骤:
1. 观察页面上的筛选条件（标签、下拉框、勾选框等）
2. 根据任务描述，点击相关的筛选条件
3. 等待页面刷新显示筛选后的结果
4. 当筛选条件都已选择完成后，使用 done 动作

成功标准: 页面显示符合任务描述的筛选结果列表"""

        nav_step = 0
        filter_done = False

        while nav_step < self.max_nav_steps and not filter_done:
            nav_step += 1
            print(f"\n[Nav] ----- 导航步骤 {nav_step} -----")

            # 1. 观察：注入 SoM 并截图
            try:
                await clear_overlay(self.page)
                await asyncio.sleep(0.2)
                snapshot = await inject_and_scan(self.page)
                screenshot_bytes, screenshot_base64 = await capture_screenshot_with_marks(self.page)

                # 保存截图
                if self.screenshots_dir:
                    screenshot_path = self.screenshots_dir / f"nav_{nav_step:03d}.png"
                    screenshot_path.write_bytes(screenshot_bytes)

                # 构建 mark_id -> xpath 映射
                mark_id_to_xpath = build_mark_id_to_xpath_map(snapshot)
                marks_text = format_marks_for_llm(snapshot)

                print(f"[Nav] 发现 {len(snapshot.marks)} 个可交互元素")
            except Exception as e:
                print(f"[Nav] 观察失败: {e}")
                break

            # 2. 决策：调用 LLM
            try:
                # 构建简化的 AgentState
                agent_state = AgentState(
                    input=RunInput(
                        start_url=self.list_url,
                        task=f"筛选操作: {self.task_description}",
                        target_text="筛选完成",
                    ),
                    step_index=nav_step,
                    page_url=self.page.url,
                    page_title=await self.page.title(),
                )

                # 解析滚动信息
                scroll_info = snapshot.scroll_info if snapshot.scroll_info else None

                # 调用 LLM 决策
                action = await self.decider.decide(
                    agent_state,
                    screenshot_base64,
                    marks_text,
                    target_found_in_page=False,
                    scroll_info=scroll_info,
                    page=self.page,
                    snapshot=snapshot,
                )

                print(f"[Nav] LLM 决策: {action.action.value}")
                print(f"[Nav] 思考: {action.thinking[:150] if action.thinking else 'N/A'}...")
                if action.mark_id:
                    print(f"[Nav] 目标元素: [{action.mark_id}] {action.target_text or ''}")
            except Exception as e:
                print(f"[Nav] 决策失败: {e}")
                break

            # 3. 执行动作
            if action.action == ActionType.DONE:
                print("[Nav] 筛选操作完成")
                filter_done = True
                break

            if action.action == ActionType.RETRY:
                print("[Nav] 重试")
                continue

            if action.action == ActionType.EXTRACT:
                print("[Nav] 收到 extract，导航模式不执行提取，按 done 处理")
                filter_done = True
                break

            try:
                # 隐藏覆盖层
                await set_overlay_visibility(self.page, False)

                # 执行动作
                result, script_step = await self.executor.execute(
                    action,
                    mark_id_to_xpath,
                    nav_step,
                )

                print(f"[Nav] 执行结果: {'成功' if result.success else '失败'}")
                if result.error:
                    print(f"[Nav] 错误: {result.error}")

                # 如果打开了新标签页，切换到新页面继续探索
                if hasattr(self.executor, "_new_page") and self.executor._new_page:
                    new_page = self.executor._new_page
                    self.page = new_page
                    self.executor.page = new_page
                    self.executor._new_page = None
                    self.list_url = self.page.url
                    print(f"[Nav] ✓ 切换到新标签页: {self.page.url}")

                # 获取被点击元素的详细信息
                clicked_element = None
                if action.mark_id:
                    clicked_element = next(
                        (m for m in snapshot.marks if m.mark_id == action.mark_id), None
                    )

                # 记录导航步骤（包含元素的详细信息）
                nav_step_record = {
                    "step": nav_step,
                    "action": action.action.value,
                    "mark_id": action.mark_id,
                    "target_text": action.target_text,
                    "thinking": action.thinking,
                    "success": result.success,
                    "text": action.text,
                    "key": action.key,
                    "url": action.url,
                    "scroll_delta": action.scroll_delta,
                    "timeout_ms": action.timeout_ms,
                }

                # 如果有点击元素，添加详细信息
                if clicked_element:
                    nav_step_record.update(
                        {
                            "clicked_element_tag": clicked_element.tag,
                            "clicked_element_text": clicked_element.text,
                            "clicked_element_href": clicked_element.href,
                            "clicked_element_role": clicked_element.role,
                            "clicked_element_xpath_candidates": [
                                {"xpath": c.xpath, "priority": c.priority, "strategy": c.strategy}
                                for c in clicked_element.xpath_candidates
                            ],
                        }
                    )

                self.nav_steps.append(nav_step_record)

                # 等待页面响应
                await asyncio.sleep(1)

            except Exception as e:
                print(f"[Nav] 执行失败: {e}")
                continue

        if filter_done:
            print(f"[Nav] ✓ 导航阶段完成，共执行 {nav_step} 步")
            await asyncio.sleep(1)
            return True
        else:
            print(f"[Nav] ⚠ 导航阶段达到最大步数 {self.max_nav_steps}，继续探索")
            return False

    async def replay_nav_steps(self, nav_steps: list[dict] = None) -> bool:
        """重放导航步骤（使用记录的 xpath）"""
        steps = nav_steps if nav_steps is not None else self.nav_steps
        if not steps:
            return False

        all_success = True
        executed_steps = 0

        for step in steps:
            if not step.get("success"):
                continue

            action_type = (step.get("action") or "").lower()
            step_success = True

            if action_type in ["click", "type"]:
                xpath_candidates = step.get("clicked_element_xpath_candidates", [])
                if not xpath_candidates:
                    step_success = False
                else:
                    xpath_candidates_sorted = sorted(
                        xpath_candidates, key=lambda x: x.get("priority", 99)
                    )
                    xpath = (
                        xpath_candidates_sorted[0].get("xpath") if xpath_candidates_sorted else None
                    )
                    if not xpath:
                        step_success = False
                    else:
                        try:
                            locator = self.page.locator(f"xpath={xpath}")
                            if await locator.count() == 0:
                                step_success = False
                            else:
                                if action_type == "click":
                                    target_text = step.get("target_text") or step.get(
                                        "clicked_element_text", ""
                                    )
                                    print(
                                        f"[Replay] 点击: {target_text[:30]}... (xpath: {xpath[:50]}...)"
                                    )
                                    try:
                                        new_page = await click_and_capture_new_page(
                                            page=self.page,
                                            locator=locator.first,
                                            click_timeout_ms=5000,
                                            expect_page_timeout_ms=3000,
                                            load_state="domcontentloaded",
                                            load_timeout_ms=10000,
                                        )
                                        if new_page is not None:
                                            self.page = new_page
                                            self.list_url = self.page.url
                                            print(f"[Replay] ✓ 切换到新标签页: {self.page.url}")
                                    except Exception:
                                        pass
                                    await asyncio.sleep(1)
                                elif action_type == "type":
                                    text = step.get("text") or ""
                                    key = step.get("key") or "Enter"
                                    print(f"[Replay] 输入: {text[:30]}... (xpath: {xpath[:50]}...)")
                                    await locator.first.click(timeout=5000)
                                    await locator.first.fill(text, timeout=5000)
                                    try:
                                        await locator.first.press(key, timeout=5000)
                                    except Exception:
                                        try:
                                            await self.page.keyboard.press(key)
                                        except Exception:
                                            pass
                                    await asyncio.sleep(0.5)
                        except Exception as e:
                            print(f"[Replay] ✗ 执行失败: {e}")
                            step_success = False
            elif action_type == "scroll":
                delta = step.get("scroll_delta") or (0, 300)
                try:
                    print(f"[Replay] 滚动: {delta}")
                    await self.page.mouse.wheel(delta[0], delta[1])
                    await asyncio.sleep(0.3)
                except Exception as e:
                    print(f"[Replay] ✗ 滚动失败: {e}")
                    step_success = False
            elif action_type == "navigate":
                url = step.get("url")
                if not url:
                    step_success = False
                else:
                    try:
                        print(f"[Replay] 导航: {url}")
                        await self.page.goto(url, wait_until="domcontentloaded", timeout=10000)
                        await asyncio.sleep(0.5)
                    except Exception as e:
                        print(f"[Replay] ✗ 导航失败: {e}")
                        step_success = False
            elif action_type == "wait":
                timeout_ms = step.get("timeout_ms") or 2000
                try:
                    print(f"[Replay] 等待: {timeout_ms}ms")
                    await self.page.wait_for_load_state("networkidle", timeout=timeout_ms)
                except Exception:
                    pass
            elif action_type == "go_back":
                try:
                    print("[Replay] 返回上一页")
                    await self.page.go_back(wait_until="domcontentloaded", timeout=10000)
                    await asyncio.sleep(0.5)
                except Exception as e:
                    print(f"[Replay] ✗ 返回失败: {e}")
                    step_success = False
            elif action_type == "go_back_tab":
                try:
                    print("[Replay] 返回上一个标签页")
                    current_page = self.page
                    raw_current = (
                        current_page.unwrap() if hasattr(current_page, "unwrap") else current_page
                    )
                    pages = list(raw_current.context.pages)
                    target_page = None
                    for candidate in reversed(pages):
                        if candidate is raw_current:
                            continue
                        target_page = candidate
                        break
                    if target_page is None:
                        step_success = False
                    else:
                        try:
                            await current_page.close()
                        except Exception:
                            pass
                        self.page = target_page
                        self.list_url = self.page.url
                        await asyncio.sleep(0.5)
                except Exception as e:
                    print(f"[Replay] ✗ 返回标签页失败: {e}")
                    step_success = False
            else:
                continue

            executed_steps += 1
            if not step_success:
                all_success = False

        return executed_steps > 0 and all_success
