"""LangGraph Agent 图定义"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from playwright.async_api import Page

from ..browser import ActionExecutor
from ..config import config
from ..llm import LLMDecider
from ..som import (
    build_mark_id_to_xpath_map,
    capture_screenshot_with_marks,
    clear_overlay,
    format_marks_for_llm,
    inject_and_scan,
    set_overlay_visibility,
)
from ..types import (
    Action,
    ActionResult,
    ActionType,
    AgentState,
    RunInput,
    ScriptStep,
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
    
    # 动作
    current_action: dict | None
    action_result: dict | None
    
    # 脚本沉淀
    script_steps: list[dict]
    
    # 历史记录（用于防止死循环）
    action_history: list[dict]  # 存储历史操作: [{step, action, mark_id, target_text, url, success}]
    blocked_actions: list[str]  # 被禁止的操作签名列表
    consecutive_scroll_count: int  # 连续滚动次数
    last_marks_hash: str  # 上一次 marks 的哈希，用于检测页面是否变化
    
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
        
        # 确保输出目录存在
        self.output_dir = Path(run_input.output_dir)
        self.screenshots_dir = self.output_dir / "screenshots"
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

    async def run(self) -> XPathScript:
        """运行 Agent 并返回 XPath 脚本"""
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
            "current_action": None,
            "action_result": None,
            "script_steps": [],
            "action_history": [],  # 历史操作记录
            "blocked_actions": [],  # 被禁止的操作签名
            "consecutive_scroll_count": 0,  # 连续滚动次数
            "last_marks_hash": "",  # 上一次页面内容哈希
            "done": False,
            "success": False,
            "error": None,
            "fail_count": 0,
            "extracted_text": None,
        }

        # 1. 导航到起始页面
        print(f"[Agent] 导航到 {self.run_input.start_url}")
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
            
            # 计算页面内容哈希（用于检测滚动后页面是否变化）
            import hashlib
            current_marks_hash = hashlib.md5(marks_text.encode()).hexdigest()[:16]
            
            # 检测滚动循环：如果上一步是滚动且页面内容未变化
            if state["action_history"]:
                last_action = state["action_history"][-1]
                if last_action.get("action") == "scroll":
                    if current_marks_hash == state["last_marks_hash"]:
                        state["consecutive_scroll_count"] += 1
                        print(f"[Observe] ⚠️ 滚动后页面无变化 (连续 {state['consecutive_scroll_count']} 次)")
                    else:
                        state["consecutive_scroll_count"] = 0
                else:
                    state["consecutive_scroll_count"] = 0
            
            state["last_marks_hash"] = current_marks_hash

            state["screenshot_base64"] = screenshot_base64
            state["marks_text"] = marks_text
            state["mark_id_to_xpath"] = mark_id_to_xpath

        except Exception as e:
            state["error"] = f"Observe failed: {str(e)}"
            print(f"[Observe] 错误: {e}")

        return state

    async def _decide(self, state: GraphState) -> GraphState:
        """决策节点：调用 LLM"""
        max_retry = 3  # 最多重试 3 次以获取非重复操作
        
        for attempt in range(max_retry):
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

                # 调用 LLM 决策，传入历史记录和禁止操作
                action = await self.decider.decide(
                    agent_state,
                    state["screenshot_base64"],
                    state["marks_text"],
                    action_history=state["action_history"],
                    blocked_actions=state["blocked_actions"],
                )

                # 生成操作签名用于死循环检测
                action_sig = self._get_action_signature(action, state["page_url"])
                
                # 检查是否为重复操作（仅针对 click 操作）
                if action.action == ActionType.CLICK and action_sig:
                    # 检查是否在禁止列表中
                    if action_sig in state["blocked_actions"]:
                        print(f"[Decide] ⚠️ 操作被禁止（死循环检测）: {action_sig}")
                        if attempt < max_retry - 1:
                            # 告知 LLM 需要重新决策
                            state["blocked_actions"].append(action_sig)
                            continue
                        else:
                            # 超过重试次数，强制滚动
                            print(f"[Decide] 重试次数耗尽，强制执行滚动操作")
                            action = Action(
                                action=ActionType.SCROLL,
                                scroll_delta=(0, 500),
                                thinking="多次尝试无效操作，执行大幅滚动探索新区域"
                            )
                    
                    # 检查近期历史中是否已执行过相同操作（在相同 URL）
                    recent_sigs = [
                        self._get_action_signature(Action(**h), h.get("url", ""))
                        for h in state["action_history"][-5:]  # 检查最近 5 步
                        if h.get("action") == "click"
                    ]
                    if action_sig in recent_sigs:
                        print(f"[Decide] ⚠️ 检测到重复操作: {action_sig}")
                        # 添加到禁止列表
                        if action_sig not in state["blocked_actions"]:
                            state["blocked_actions"].append(action_sig)
                        if attempt < max_retry - 1:
                            continue
                        else:
                            print(f"[Decide] 重试次数耗尽，强制执行滚动操作")
                            action = Action(
                                action=ActionType.SCROLL,
                                scroll_delta=(0, 500),
                                thinking="检测到重复点击循环，执行大幅滚动探索新区域"
                            )
                
                # 检查滚动循环：连续多次滚动但页面无变化
                if action.action == ActionType.SCROLL:
                    if state["consecutive_scroll_count"] >= 3:
                        print(f"[Decide] ⚠️ 检测到滚动循环（连续 {state['consecutive_scroll_count']} 次滚动无变化）")
                        print(f"[Decide] 禁止继续滚动，要求 LLM 尝试其他操作")
                        # 添加滚动禁止提示
                        if "scroll_blocked" not in state["blocked_actions"]:
                            state["blocked_actions"].append("scroll_blocked:页面已到底或无法滚动")
                        if attempt < max_retry - 1:
                            continue
                        else:
                            # 强制返回上一页或点击第一个可点击元素
                            print(f"[Decide] 重试次数耗尽，强制执行返回操作")
                            action = Action(
                                action=ActionType.DONE,
                                thinking="页面已探索完毕，无法找到目标内容，在当前详情页中不存在统一交易标识码"
                            )

                print(f"[Decide] LLM 决策: {action.action.value}")
                print(f"[Decide] 思考: {action.thinking[:200] if action.thinking else 'N/A'}...")
                if action.mark_id:
                    print(f"[Decide] 目标元素: [{action.mark_id}] {action.target_text or ''}")

                state["current_action"] = action.model_dump()
                break  # 成功获取有效操作，退出重试循环

            except Exception as e:
                state["error"] = f"Decide failed: {str(e)}"
                print(f"[Decide] 错误: {e}")
                break

        return state
    
    def _get_action_signature(self, action: Action, url: str) -> str | None:
        """生成操作签名，用于死循环检测"""
        if action.action == ActionType.CLICK:
            # 对于 click 操作，使用 (action_type, target_text, url_path) 作为签名
            from urllib.parse import urlparse
            url_path = urlparse(url).path if url else ""
            target = action.target_text or f"mark_{action.mark_id}"
            return f"click:{target}:{url_path}"
        elif action.action == ActionType.TYPE:
            return f"type:{action.text}:{action.mark_id}"
        return None


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
            
            # 记录历史操作（用于死循环检测和 LLM 历史回顾）
            history_entry = {
                "step": state["step_index"],
                "action": action.action.value,
                "mark_id": action.mark_id,
                "target_text": action.target_text,
                "url": state["page_url"],
                "success": result.success,
            }
            state["action_history"].append(history_entry)

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

        # 检查是否已提取到目标文本
        if state["extracted_text"]:
            target = state["target_text"]
            if target.lower() in state["extracted_text"].lower():
                state["done"] = True
                state["success"] = True
                print(f"[Check] 已提取到目标文本: {target}")

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
