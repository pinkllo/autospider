"""导航处理模块 - 负责导航阶段和步骤重放"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from autospider.platform.browser.accessibility import get_accessibility_text
from autospider.platform.browser.actions import ActionExecutor
from autospider.platform.browser.click_utils import click_and_capture_new_page
from autospider.platform.browser.page_handle import pages_match, resolve_previous_page
from autospider.contexts.collection.infrastructure.decision_context_format import (
    format_decision_context as _format_navigation_decision_context,
)
from autospider.platform.observability.logger import get_logger
from autospider.platform.browser.som import (
    build_mark_id_to_xpath_map,
    capture_screenshot_with_marks,
    clear_overlay,
    inject_and_scan,
    set_overlay_visibility,
)
from autospider.platform.shared_kernel.types import ActionType, AgentState, RunInput
from autospider.contexts.planning import format_execution_brief
from autospider.composition.graph.recovery import build_recovery_directive

if TYPE_CHECKING:
    from pathlib import Path
    from playwright.async_api import Page
    from autospider.platform.llm.decider import LLMDecider


logger = get_logger(__name__)
_ACTIVE_STATE_TOKENS = ("active", "selected", "current", "checked")
_ARIA_CURRENT_ACTIVE_VALUES = {"true", "page", "step", "location"}
_REPLAY_LOCATOR_POLL_INTERVALS_MS = (0, 300, 800, 1500)


@dataclass(slots=True)
class ReplayNavigationResult:
    success: bool
    executed_steps: int = 0
    failed_step: int | None = None
    failure_reason: str = ""
    validation_status: str = "not_requested"
    required_validation_steps: int = 0
    validated_steps: int = 0

    def __bool__(self) -> bool:
        return self.success


def build_navigation_task_plan(
    *,
    task_description: str,
    execution_brief: dict | None = None,
    decision_context: dict[str, object] | None = None,
) -> str:
    sections = [
        "任务分析: 你需要先在列表页进行筛选操作，达到以下目标：",
        str(task_description or ""),
        "",
        "执行简报:",
        format_execution_brief(execution_brief),
        "",
        "决策上下文:",
        _format_navigation_decision_context(decision_context),
        "",
        "执行步骤:",
        "1. 观察页面上的筛选条件（标签、下拉框、勾选框等）",
        "2. 根据任务描述和决策上下文，点击相关的筛选条件",
        "3. 等待页面刷新显示筛选后的结果",
        "4. 当筛选条件都已选择完成后，使用 done 动作",
        "",
        "成功标准: 页面显示符合任务描述的筛选结果列表",
    ]
    return "\n".join(sections)


class NavigationHandler:
    """导航处理器，负责导航阶段的筛选操作和步骤重放"""

    def __init__(
        self,
        page: "Page",
        list_url: str,
        task_description: str,
        max_nav_steps: int,
        execution_brief: dict | None = None,
        decision_context: dict | None = None,
        decider: "LLMDecider" = None,
        screenshots_dir: "Path" = None,
    ):
        self.page = page
        self.list_url = list_url
        self.task_description = task_description
        self.max_nav_steps = max_nav_steps
        self.execution_brief = dict(execution_brief or {})
        self.decision_context = dict(decision_context or {})
        self.decider = decider
        self.screenshots_dir = screenshots_dir
        self.executor: ActionExecutor | None = None
        self.nav_steps: list[dict] = []

    def _build_retry_failure_entry(self, nav_step: int, failure_record: dict) -> dict[str, object]:
        directive = build_recovery_directive(
            failure_record=failure_record,
            failure_count=0,
            max_retries=0,
        )
        return {
            "step": nav_step,
            "action": ActionType.RETRY.value,
            "thinking": "contract_violation",
            "success": False,
            "failure_record": dict(failure_record),
            "recovery_directive": {
                "action": directive.action,
                "reason": directive.reason,
            },
        }

    def _handle_retry_action(self, nav_step: int, action) -> bool:
        if not action.failure_record:
            logger.info("[Nav] 重试")
            return False
        failure_record = dict(action.failure_record)
        entry = self._build_retry_failure_entry(nav_step, failure_record)
        entry["thinking"] = action.thinking
        self.nav_steps.append(entry)
        logger.error(
            "[Nav] 决策失败，停止导航: category=%s directive=%s",
            failure_record.get("category"),
            entry["recovery_directive"]["action"],
        )
        return True

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
        self.decider.task_plan = build_navigation_task_plan(
            task_description=self.task_description,
            execution_brief=self.execution_brief,
            decision_context=self.decision_context,
        )

        nav_step = 0
        filter_done = False

        while nav_step < self.max_nav_steps and not filter_done:
            nav_step += 1
            logger.info("[Nav] ----- 导航步骤 %s -----", nav_step)

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

                logger.info("[Nav] 发现 %s 个可交互元素", len(snapshot.marks))
            except Exception as e:
                logger.error("[Nav] 观察失败: %s", e)
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

                # 获取无障碍文本锚点
                accessibility_text = ""
                try:
                    accessibility_text = await get_accessibility_text(self.page)
                except Exception:
                    pass

                # 调用 LLM 决策
                action = await self.decider.decide(
                    agent_state,
                    screenshot_base64,
                    target_found_in_page=False,
                    scroll_info=scroll_info,
                    page=self.page,
                    snapshot=snapshot,
                    page_accessibility_text=accessibility_text,
                )

                logger.info("[Nav] LLM 决策: %s", action.action.value)
                logger.info(
                    "[Nav] 思考: %s...",
                    action.thinking[:150] if action.thinking else "N/A",
                )
                if action.mark_id:
                    logger.info(
                        "[Nav] 目标元素: [%s] %s",
                        action.mark_id,
                        action.target_text or "",
                    )
            except Exception as e:
                logger.error("[Nav] 决策失败: %s", e)
                break

            # 3. 执行动作
            if action.action == ActionType.DONE:
                logger.info("[Nav] 筛选操作完成")
                filter_done = True
                break

            if action.action == ActionType.RETRY:
                if self._handle_retry_action(nav_step, action):
                    break
                continue

            if action.action == ActionType.EXTRACT:
                logger.warning("[Nav] 收到 extract，导航模式不执行提取，按 done 处理")
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

                logger.info("[Nav] 执行结果: %s", "成功" if result.success else "失败")
                if result.error:
                    logger.warning("[Nav] 错误: %s", result.error)

                # 如果打开了新标签页，切换到新页面继续探索
                if hasattr(self.executor, "_new_page") and self.executor._new_page:
                    new_page = self.executor._new_page
                    self.page = new_page
                    self.executor.page = new_page
                    self.executor._new_page = None
                    self.list_url = self.page.url
                    logger.info("[Nav] ✓ 切换到新标签页: %s", self.page.url)

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
                logger.error("[Nav] 执行失败: %s", e)
                continue

        if filter_done:
            logger.info("[Nav] ✓ 导航阶段完成，共执行 %s 步", nav_step)
            await asyncio.sleep(1)
            return True
        else:
            logger.warning("[Nav] ⚠ 导航阶段达到最大步数 %s，继续探索", self.max_nav_steps)
            return False

    async def replay_nav_steps(self, nav_steps: list[dict] = None) -> ReplayNavigationResult:
        """重放导航步骤（使用记录的 xpath）"""
        steps = nav_steps if nav_steps is not None else self.nav_steps
        if not steps:
            return ReplayNavigationResult(success=False, failure_reason="no_replay_steps")

        executed_steps = 0
        required_validation_steps = 0
        validated_steps = 0

        for step_index, step in enumerate(steps, start=1):
            if not step.get("success"):
                continue

            action_type = (step.get("action") or "").lower()
            step_success = True
            failure_reason = "replay_step_failed"
            validation = (
                step.get("state_validation")
                if isinstance(step.get("state_validation"), dict)
                else {}
            )
            validation_kind = str(validation.get("kind") or "").strip().lower()
            if validation_kind == "same_page_activation":
                required_validation_steps += 1

            if action_type in ["click", "type"]:
                locator = await self._resolve_replay_locator(step)
                if locator is None:
                    step_success = False
                    failure_reason = "replay_locator_not_found"
                else:
                    try:
                        if action_type == "click":
                            target_text = step.get("target_text") or step.get(
                                "clicked_element_text", ""
                            )
                            logger.info(
                                "[Replay] 点击: %s...",
                                target_text[:30],
                            )
                            try:
                                new_page = await click_and_capture_new_page(
                                    page=self.page,
                                    locator=locator,
                                    click_timeout_ms=5000,
                                    expect_page_timeout_ms=3000,
                                    load_state="domcontentloaded",
                                    load_timeout_ms=10000,
                                )
                                if new_page is not None:
                                    self.page = new_page
                                    self.list_url = self.page.url
                                    logger.info("[Replay] ✓ 切换到新标签页: %s", self.page.url)
                            except Exception as exc:
                                logger.debug("[Replay] 点击后未捕获新页面: %s", exc)
                            await asyncio.sleep(1)
                        elif action_type == "type":
                            text = step.get("text") or ""
                            key = step.get("key") or "Enter"
                            logger.info(
                                "[Replay] 输入: %s...",
                                text[:30],
                            )
                            await locator.click(timeout=5000)
                            await locator.fill(text, timeout=5000)
                            try:
                                await locator.press(key, timeout=5000)
                            except Exception:
                                try:
                                    await self.page.keyboard.press(key)
                                except Exception:
                                    pass
                            await asyncio.sleep(0.5)
                    except Exception as e:
                        logger.error("[Replay] ✗ 执行失败: %s", e)
                        step_success = False
                        failure_reason = f"replay_{action_type}_failed"
            elif action_type == "scroll":
                delta = step.get("scroll_delta") or (0, 300)
                try:
                    logger.info("[Replay] 滚动: %s", delta)
                    await self.page.mouse.wheel(delta[0], delta[1])
                    await asyncio.sleep(0.3)
                except Exception as e:
                    logger.error("[Replay] ✗ 滚动失败: %s", e)
                    step_success = False
                    failure_reason = "replay_scroll_failed"
            elif action_type == "navigate":
                url = step.get("url")
                if not url:
                    step_success = False
                    failure_reason = "replay_url_missing"
                else:
                    try:
                        logger.info("[Replay] 导航: %s", url)
                        await self.page.goto(url, wait_until="domcontentloaded", timeout=10000)
                        await asyncio.sleep(0.5)
                    except Exception as e:
                        logger.error("[Replay] ✗ 导航失败: %s", e)
                        step_success = False
                        failure_reason = "replay_navigate_failed"
            elif action_type == "wait":
                timeout_ms = step.get("timeout_ms") or 2000
                try:
                    logger.info("[Replay] 等待: %sms", timeout_ms)
                    await self.page.wait_for_load_state("networkidle", timeout=timeout_ms)
                except Exception:
                    pass
            elif action_type == "go_back":
                try:
                    logger.info("[Replay] 返回上一页")
                    await self.page.go_back(wait_until="domcontentloaded", timeout=10000)
                    await asyncio.sleep(0.5)
                except Exception as e:
                    logger.error("[Replay] ✗ 返回失败: %s", e)
                    step_success = False
                    failure_reason = "replay_go_back_failed"
            elif action_type == "go_back_tab":
                try:
                    logger.info("[Replay] 返回上一个标签页")
                    current_page = self.page
                    target_page = await resolve_previous_page(current_page)
                    if target_page is None:
                        step_success = False
                        failure_reason = "replay_tab_not_found"
                    else:
                        try:
                            if not pages_match(current_page, target_page):
                                await current_page.close()
                        except Exception:
                            pass
                        self.page = target_page
                        self.list_url = self.page.url
                        await asyncio.sleep(0.5)
                except Exception as e:
                    logger.error("[Replay] ✗ 返回标签页失败: %s", e)
                    step_success = False
                    failure_reason = "replay_go_back_tab_failed"
            else:
                continue

            executed_steps += 1
            if not step_success:
                return ReplayNavigationResult(
                    success=False,
                    executed_steps=executed_steps,
                    failed_step=step_index,
                    failure_reason=failure_reason,
                    validation_status="failed" if required_validation_steps else "not_requested",
                    required_validation_steps=required_validation_steps,
                    validated_steps=validated_steps,
                )
            if validation_kind == "same_page_activation":
                if not await self._validate_same_page_activation(step):
                    return ReplayNavigationResult(
                        success=False,
                        executed_steps=executed_steps,
                        failed_step=step_index,
                        failure_reason="same_page_state_not_activated",
                        validation_status="failed",
                        required_validation_steps=required_validation_steps,
                        validated_steps=validated_steps,
                    )
                validated_steps += 1

        if executed_steps == 0:
            return ReplayNavigationResult(success=False, failure_reason="no_replayable_steps")
        validation_status = "passed" if required_validation_steps else "not_requested"
        return ReplayNavigationResult(
            success=True,
            executed_steps=executed_steps,
            validation_status=validation_status,
            required_validation_steps=required_validation_steps,
            validated_steps=validated_steps,
        )

    async def _resolve_replay_locator(self, step: dict):
        xpath_candidates = list(step.get("clicked_element_xpath_candidates") or [])
        target_text = str(step.get("target_text") or step.get("clicked_element_text") or "").strip()
        xpath_candidates_sorted = sorted(xpath_candidates, key=lambda x: x.get("priority", 99))

        for wait_ms in _REPLAY_LOCATOR_POLL_INTERVALS_MS:
            if wait_ms:
                await self._wait_for_replay_locator(wait_ms)
            locator = await self._resolve_replay_locator_once(
                xpath_candidates_sorted=xpath_candidates_sorted,
                target_text=target_text,
            )
            if locator is not None:
                return locator
        return None

    async def _resolve_replay_locator_once(
        self,
        *,
        xpath_candidates_sorted: list[dict],
        target_text: str,
    ):
        for candidate in xpath_candidates_sorted:
            xpath = str(candidate.get("xpath") or "").strip()
            if not xpath:
                continue
            locator = self.page.locator(f"xpath={xpath}")
            count = await locator.count()
            if count == 0:
                continue
            if count == 1:
                return locator.first
            if target_text:
                matched = await self._pick_locator_by_text(locator, target_text, count)
                if matched is not None:
                    return matched
        if not target_text:
            return None
        return await self._find_replay_text_fallback(target_text)

    async def _find_replay_text_fallback(self, target_text: str):
        fallback = self.page.get_by_text(target_text, exact=True)
        exact_count = await fallback.count()
        if exact_count == 1:
            return fallback.first
        if exact_count > 1:
            matched = await self._pick_locator_by_text(fallback, target_text, exact_count)
            if matched is not None:
                return matched

        contains = self.page.get_by_text(target_text, exact=False)
        contains_count = await contains.count()
        if contains_count == 1:
            return contains.first
        if contains_count > 1:
            matched = await self._pick_locator_by_text(contains, target_text, contains_count)
            if matched is not None:
                return matched
        return None

    async def _wait_for_replay_locator(self, wait_ms: int) -> None:
        wait_for_timeout = getattr(self.page, "wait_for_timeout", None)
        if callable(wait_for_timeout):
            try:
                await wait_for_timeout(wait_ms)
                return
            except Exception:
                pass
        await asyncio.sleep(wait_ms / 1000)

    async def _pick_locator_by_text(self, locator, target_text: str, count: int | None = None):
        normalized_target = "".join(str(target_text or "").split())
        if not normalized_target:
            return None
        total = count if count is not None else await locator.count()
        for index in range(total):
            candidate = locator.nth(index)
            try:
                text = await candidate.inner_text(timeout=1000)
            except Exception:
                text = ""
            normalized_text = "".join(str(text or "").split())
            if normalized_target and normalized_target in normalized_text:
                return candidate
        return None

    async def _validate_same_page_activation(self, step: dict) -> bool:
        interaction_xpath = self._get_interaction_xpath(step)
        if not interaction_xpath:
            return False
        state = await self._get_interaction_state(interaction_xpath)
        return self._is_active_interaction_state(state)

    def _get_interaction_xpath(self, step: dict) -> str:
        validation = (
            step.get("state_validation") if isinstance(step.get("state_validation"), dict) else {}
        )
        interaction_xpath = str(validation.get("interaction_xpath") or "").strip()
        if interaction_xpath:
            return interaction_xpath
        xpath_candidates = list(step.get("clicked_element_xpath_candidates") or [])
        xpath_candidates_sorted = sorted(
            xpath_candidates, key=lambda item: item.get("priority", 99)
        )
        for candidate in xpath_candidates_sorted:
            xpath = str(candidate.get("xpath") or "").strip()
            if xpath:
                return xpath
        return ""

    async def _get_interaction_state(self, xpath: str) -> dict[str, str]:
        try:
            state = await self.page.evaluate(
                """(xpath) => {
                    const result = document.evaluate(
                        xpath, document, null,
                        XPathResult.FIRST_ORDERED_NODE_TYPE, null
                    );
                    const el = result.singleNodeValue;
                    if (!el) return {};
                    return {
                        class_name: String(el.className || ''),
                        aria_selected: String(el.getAttribute('aria-selected') || ''),
                        aria_current: String(el.getAttribute('aria-current') || ''),
                        data_state: String(el.getAttribute('data-state') || ''),
                    };
                }""",
                xpath,
            )
            return dict(state or {})
        except Exception:
            return {}

    def _is_active_interaction_state(self, state: dict[str, str] | None) -> bool:
        if not state:
            return False
        class_name = str(state.get("class_name") or "").lower()
        if any(token in class_name for token in _ACTIVE_STATE_TOKENS):
            return True
        if str(state.get("aria_selected") or "").lower() == "true":
            return True
        if str(state.get("aria_current") or "").lower() in _ARIA_CURRENT_ACTIVE_VALUES:
            return True
        return str(state.get("data_state") or "").lower() in _ACTIVE_STATE_TOKENS
