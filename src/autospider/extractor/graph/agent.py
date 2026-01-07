"""LangGraph Agent 图定义"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from playwright.async_api import Page

from ...common.browser import ActionExecutor
from ...common.config import config
from ..llm import LLMDecider
from ..llm.planner import TaskPlanner
from ...common.som import (
    build_mark_id_to_xpath_map,
    capture_screenshot_with_marks,
    clear_overlay,
    format_marks_for_llm,
    inject_and_scan,
    set_overlay_visibility,
)
from ...common.types import (
    Action,
    ActionResult,
    ActionType,
    AgentState,
    RunInput,
    ScriptStep,
    ScrollInfo,
    SoMSnapshot,
    XPathScript,
)


# ============================================================================
# LangGraph 状态定义（使用 TypedDict）
# ============================================================================


class GraphState(TypedDict):
    """LangGraph 状态（简化版，用于图传递）"""
    
    # 输入
    start_url: str
    task: str
    target_text: str
    max_steps: int
    output_dir: str
    
    # 运行时状态
    step_index: int
    page_url: str
    page_title: str
    
    # 观察结果
    screenshot_base64: str
    marks_text: str
    mark_id_to_xpath: dict[int, list[str]]
    scroll_info: dict | None  # 页面滚动状态
    
    # 动作
    current_action: dict | None
    action_result: dict | None
    
    # 脚本沉淀
    script_steps: list[dict]
    
    # 状态标志
    done: bool
    success: bool
    error: str | None
    fail_count: int
    extracted_text: str | None


# ============================================================================
# Agent 运行器
# ============================================================================


class SoMAgent:
    """SoM 纯视觉 Agent"""

    def __init__(
        self,
        page: Page,
        run_input: RunInput,
    ):
        self.page = page
        self.run_input = run_input
        self.executor = ActionExecutor(page)
        self.decider = LLMDecider()
        self.planner = TaskPlanner()
        
        # 确保输出目录存在
        self.output_dir = Path(run_input.output_dir)
        self.screenshots_dir = self.output_dir / "screenshots"
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        
        # 目标文本匹配结果
        self.target_found_in_page = False
        self.target_element_info: dict | None = None

    async def run(self) -> XPathScript:
        """运行 Agent 并返回 XPath 脚本"""
        # 0. 任务规划
        print("[Agent] 正在分析任务并生成执行计划...")
        try:
            plan = await self.planner.plan(
                self.run_input.start_url,
                self.run_input.task,
                self.run_input.target_text,
            )
            print(f"[Plan] 任务分析: {plan.task_analysis}")
            print(f"[Plan] 执行步骤:")
            for i, step in enumerate(plan.steps, 1):
                print(f"  {i}. {step}")
            print(f"[Plan] 成功标准: {plan.success_criteria}")
            
            # 将计划传递给决策器
            plan_text = f"任务分析: {plan.task_analysis}\n"
            plan_text += "执行步骤:\n" + "\n".join(f"  {i}. {s}" for i, s in enumerate(plan.steps, 1))
            plan_text += f"\n成功标准: {plan.success_criteria}"
            self.decider.task_plan = plan_text
        except Exception as e:
            print(f"[Plan] 规划失败，继续执行: {e}")
        
        # 初始化状态
        state: GraphState = {
            "start_url": self.run_input.start_url,
            "task": self.run_input.task,
            "target_text": self.run_input.target_text,
            "max_steps": self.run_input.max_steps,
            "output_dir": self.run_input.output_dir,
            "step_index": 0,
            "page_url": "",
            "page_title": "",
            "screenshot_base64": "",
            "marks_text": "",
            "mark_id_to_xpath": {},
            "scroll_info": None,
            "current_action": None,
            "action_result": None,
            "script_steps": [],
            "done": False,
            "success": False,
            "error": None,
            "fail_count": 0,
            "extracted_text": None,
        }

        # 1. 导航到起始页面
        print(f"\n[Agent] 导航到 {self.run_input.start_url}")
        await self.page.goto(
            self.run_input.start_url,
            wait_until="domcontentloaded",
            timeout=30000,
        )
        await asyncio.sleep(1)  # 等待页面稳定

        # 主循环
        while not state["done"] and state["step_index"] < state["max_steps"]:
            print(f"\n[Agent] ===== 步骤 {state['step_index'] + 1} =====")
            
            # 2. Observe: 注入 SoM 并截图
            state = await self._observe(state)
            if state["error"]:
                break
            
            # 2.5 检查页面中是否存在目标文本（精确匹配）
            await self._check_target_text_in_page(state)

            # 3. Decide: 调用 LLM 决策
            state = await self._decide(state)
            if state["error"]:
                break

            # 4. Act: 执行动作
            state = await self._act(state)

            # 5. Check: 检查是否完成
            state = self._check_done(state)

            state["step_index"] += 1

        # 生成最终脚本
        script = self._generate_script(state)
        return script

    async def _observe(self, state: GraphState) -> GraphState:
        """观察节点：注入 SoM + 截图"""
        try:
            # 等待页面稳定
            try:
                await self.page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass

            # 更新页面信息
            state["page_url"] = self.page.url
            state["page_title"] = await self.page.title()

            # 清除旧的覆盖层
            await clear_overlay(self.page)
            await asyncio.sleep(0.2)

            # 注入 SoM 并扫描
            snapshot = await inject_and_scan(self.page)
            print(f"[Observe] 发现 {len(snapshot.marks)} 个可交互元素")

            # 截图（包含 SoM 标注）
            screenshot_bytes, screenshot_base64 = await capture_screenshot_with_marks(self.page)

            # 保存截图
            screenshot_path = self.screenshots_dir / f"step_{state['step_index']:03d}.png"
            screenshot_path.write_bytes(screenshot_bytes)
            print(f"[Observe] 截图已保存: {screenshot_path}")

            # 构建 mark_id -> xpath 映射
            mark_id_to_xpath = build_mark_id_to_xpath_map(snapshot)

            # 格式化 marks 供 LLM 使用
            marks_text = format_marks_for_llm(snapshot)

            state["screenshot_base64"] = screenshot_base64
            state["marks_text"] = marks_text
            state["mark_id_to_xpath"] = mark_id_to_xpath
            
            # 保存滚动信息
            if snapshot.scroll_info:
                state["scroll_info"] = snapshot.scroll_info.model_dump()
                print(f"[Observe] 滚动状态: {snapshot.scroll_info.scroll_percent}% | 底部: {snapshot.scroll_info.is_at_bottom}")
            else:
                state["scroll_info"] = None

        except Exception as e:
            state["error"] = f"Observe failed: {str(e)}"
            print(f"[Observe] 错误: {e}")

        return state

    async def _check_target_text_in_page(self, state: GraphState) -> None:
        """检查页面中是否存在目标文本（精确匹配）"""
        target_text = state["target_text"]
        try:
            # 获取页面全部文本内容
            page_text = await self.page.evaluate("document.body.innerText")
            
            # 精确匹配（区分大小写）
            if target_text in page_text:
                self.target_found_in_page = True
                print(f"[Check] ✓ 页面中发现目标文本「{target_text}」")
                
                # 尝试定位包含目标文本的元素
                try:
                    # 使用 XPath 查找包含目标文本的元素
                    locator = self.page.locator(f"text={target_text}").first
                    if await locator.count() > 0:
                        # 获取元素信息
                        bbox = await locator.bounding_box()
                        text = await locator.inner_text()
                        self.target_element_info = {
                            "text": text[:200] if text else "",
                            "bbox": bbox,
                        }
                        print(f"[Check] 目标元素内容: {text[:100] if text else 'N/A'}...")
                except Exception:
                    pass
            else:
                self.target_found_in_page = False
                
        except Exception as e:
            print(f"[Check] 检查目标文本时出错: {e}")
            self.target_found_in_page = False

    async def _decide(self, state: GraphState) -> GraphState:
        """决策节点：调用 LLM"""
        try:
            # 构建简化的 AgentState 供 LLM 使用
            agent_state = AgentState(
                input=self.run_input,
                step_index=state["step_index"],
                page_url=state["page_url"],
                page_title=state["page_title"],
                last_action=Action(**state["current_action"]) if state["current_action"] else None,
                last_result=ActionResult(**state["action_result"]) if state["action_result"] else None,
            )
            
            # 解析滚动信息
            scroll_info = None
            if state.get("scroll_info"):
                scroll_info = ScrollInfo(**state["scroll_info"])

            # 调用 LLM 决策（传入目标文本是否已找到和滚动信息）
            action = await self.decider.decide(
                agent_state,
                state["screenshot_base64"],
                state["marks_text"],
                target_found_in_page=self.target_found_in_page,
                scroll_info=scroll_info,
            )

            print(f"[Decide] LLM 决策: {action.action.value}")
            print(f"[Decide] 思考: {action.thinking[:200] if action.thinking else 'N/A'}...")
            if action.mark_id:
                print(f"[Decide] 目标元素: [{action.mark_id}] {action.target_text or ''}")

            state["current_action"] = action.model_dump()

        except Exception as e:
            state["error"] = f"Decide failed: {str(e)}"
            print(f"[Decide] 错误: {e}")

        return state

    async def _act(self, state: GraphState) -> GraphState:
        """执行节点：执行动作"""
        if not state["current_action"]:
            return state

        action = Action(**state["current_action"])

        # 特殊处理 done 和 retry
        if action.action == ActionType.DONE:
            state["done"] = True
            state["success"] = True
            print("[Act] 任务完成")
            return state

        if action.action == ActionType.RETRY:
            state["fail_count"] += 1
            print(f"[Act] 重试 (失败次数: {state['fail_count']})")
            if state["fail_count"] >= 3:
                state["error"] = "Too many retries"
            return state

        try:
            # 隐藏覆盖层以便点击（虽然是 pointer-events: none，但为保险起见）
            await set_overlay_visibility(self.page, False)

            # 执行动作
            result, script_step = await self.executor.execute(
                action,
                state["mark_id_to_xpath"],
                state["step_index"],
            )

            # 检查是否有新页面打开（处理 target="_blank" 链接）
            if hasattr(self.executor, '_new_page') and self.executor._new_page:
                print(f"[Act] 检测到新标签页，切换到新页面")
                self.page = self.executor._new_page
                self.executor.page = self.executor._new_page
                self.executor._new_page = None

            print(f"[Act] 执行结果: {'成功' if result.success else '失败'}")
            if result.error:
                print(f"[Act] 错误: {result.error}")
            if result.extracted_text:
                print(f"[Act] 提取内容: {result.extracted_text[:100]}...")
                state["extracted_text"] = result.extracted_text

            state["action_result"] = result.model_dump()

            # 记录脚本步骤
            if script_step:
                script_step.screenshot_context = f"step_{state['step_index']:03d}.png"
                state["script_steps"].append(script_step.model_dump())

            # 更新失败计数
            if not result.success:
                state["fail_count"] += 1
            else:
                state["fail_count"] = 0

            # 等待页面响应
            await asyncio.sleep(0.5)

        except Exception as e:
            state["error"] = f"Act failed: {str(e)}"
            state["fail_count"] += 1
            print(f"[Act] 错误: {e}")

        return state

    def _check_done(self, state: GraphState) -> GraphState:
        """检查是否完成"""
        # 检查失败次数
        if state["fail_count"] >= 3:
            state["done"] = True
            state["error"] = state["error"] or "Too many failures"
            print("[Check] 失败次数过多，终止")
            return state

        # 检查是否已提取到目标文本（精确匹配）
        if state["extracted_text"]:
            target = state["target_text"]
            # 精确匹配（区分大小写）
            if target in state["extracted_text"]:
                state["done"] = True
                state["success"] = True
                print(f"[Check] ✓ 已精确匹配到目标文本: {target}")
            else:
                print(f"[Check] 提取的内容中未精确匹配到「{target}」")

        return state

    def _generate_script(self, state: GraphState) -> XPathScript:
        """生成最终的 XPath 脚本"""
        script = XPathScript(
            task=state["task"],
            start_url=state["start_url"],
            target_text=state["target_text"],
            steps=[ScriptStep(**s) for s in state["script_steps"]],
            extracted_result=state["extracted_text"],
            created_at=datetime.now().isoformat(),
        )
        return script


# ============================================================================
# 便捷函数
# ============================================================================


async def run_agent(page: Page, run_input: RunInput) -> XPathScript:
    """运行 Agent 的便捷函数"""
    agent = SoMAgent(page, run_input)
    return await agent.run()
