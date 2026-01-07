"""多模态 LLM 决策器"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_openai import ChatOpenAI

from ...common.config import config
from ...common.types import Action, ActionType, ScrollInfo
from .prompt_template import render_template

if TYPE_CHECKING:
    from ...common.types import AgentState, SoMSnapshot


# ============================================================================
# Prompt 模板文件路径
# ============================================================================

PROMPT_TEMPLATE_PATH = str(Path(__file__).parent.parent.parent.parent.parent / "prompts" / "decider.yaml")


# ============================================================================
# LLM 决策器
# ============================================================================


class LLMDecider:
    """多模态 LLM 决策器"""

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        model: str | None = None,
        history_screenshots: int = 3,  # 发送最近几步的截图
    ):
        self.api_key = api_key or config.llm.api_key
        self.api_base = api_base or config.llm.api_base
        self.model = model or config.llm.model

        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not set")

        self.llm = ChatOpenAI(
            api_key=self.api_key,
            base_url=self.api_base,
            model=self.model,
            temperature=config.llm.temperature,
            max_tokens=config.llm.max_tokens,
        )
        
        # 任务计划（由 planner 设置）
        self.task_plan: str | None = None
        
        # 历史记录（用于避免重复操作）
        self.action_history: list[dict] = []
        
        # 滚动计数器（避免无限滚动）
        self.scroll_count: int = 0
        self.max_consecutive_scrolls: int = 5
        
        # 页面滚动历史：记录每个页面的滚动状态
        # key: page_url, value: {"fully_scrolled": bool, "visited_positions": set}
        self.page_scroll_history: dict[str, dict] = {}
        
        # 当前页面 URL（用于检测页面切换）
        self.current_page_url: str = ""
        
        # 循环检测：记录最近的操作序列
        self.recent_action_signatures: list[str] = []
        self.max_signature_history: int = 10
        
        # 截图历史：保存最近几步的截图用于发送给 LLM
        self.history_screenshots: int = history_screenshots
        self.screenshot_history: list[dict] = []  # [{step, screenshot_base64, action, page_url}]

    async def decide(
        self,
        state: "AgentState",
        screenshot_base64: str,
        marks_text: str,
        target_found_in_page: bool = False,
        scroll_info: ScrollInfo | None = None,
    ) -> Action:
        """
        根据当前状态和截图决定下一步操作
        
        Args:
            state: Agent 状态
            screenshot_base64: 带 SoM 标注的截图（Base64）
            marks_text: 格式化的 marks 文本描述
            target_found_in_page: 页面中是否发现了目标文本
            scroll_info: 页面滚动状态信息
        
        Returns:
            下一步操作
        """
        # 构建用户消息
        user_content = self._build_user_message(state, marks_text, target_found_in_page, scroll_info)

        # 构建消息内容（包含历史截图 + 当前截图）
        message_content = self._build_multimodal_content(
            user_content, 
            screenshot_base64, 
            state.step_index
        )

        # 从模板文件加载 system_prompt
        system_prompt = render_template(
            PROMPT_TEMPLATE_PATH,
            section="system_prompt",
        )

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=message_content),
        ]

        # 调用 LLM
        response = await self.llm.ainvoke(messages)
        response_text = response.content

        # 解析响应
        action = self._parse_response(response_text)
        
        # 更新页面滚动历史
        page_url = state.page_url
        if page_url != self.current_page_url:
            # 页面切换了，重置滚动计数
            self.current_page_url = page_url
            self.scroll_count = 0
        
        # 跟踪滚动次数和页面滚动状态
        if action.action == ActionType.SCROLL:
            self.scroll_count += 1
            
            # 更新页面滚动历史
            if page_url not in self.page_scroll_history:
                self.page_scroll_history[page_url] = {
                    "fully_scrolled": False,
                    "reached_bottom": False,
                    "reached_top_after_bottom": False,
                    "scroll_directions": [],
                }
            
            # 记录滚动方向
            if action.scroll_delta:
                direction = "down" if action.scroll_delta[1] > 0 else "up"
                self.page_scroll_history[page_url]["scroll_directions"].append(direction)
            
            # 如果连续滚动太多次，强制尝试其他操作
            if self.scroll_count >= self.max_consecutive_scrolls:
                print(f"[Decide] 警告: 已连续滚动 {self.scroll_count} 次，可能需要其他操作")
        else:
            self.scroll_count = 0  # 重置滚动计数
        
        # 更新页面滚动完成状态（基于 scroll_info）
        if scroll_info and page_url in self.page_scroll_history:
            history = self.page_scroll_history[page_url]
            if scroll_info.is_at_bottom:
                history["reached_bottom"] = True
            if history["reached_bottom"] and scroll_info.is_at_top:
                history["reached_top_after_bottom"] = True
                history["fully_scrolled"] = True
                print(f"[Decide] 📜 页面已完整滚动: {page_url[:50]}...")
        
        # 生成操作签名用于循环检测
        action_sig = f"{action.action.value}:{action.mark_id}:{action.target_text}"
        self.recent_action_signatures.append(action_sig)
        if len(self.recent_action_signatures) > self.max_signature_history:
            self.recent_action_signatures.pop(0)
        
        # 检测循环模式
        loop_detected = self._detect_loop()
        if loop_detected:
            print(f"[Decide] ⚠️ 检测到循环操作模式！")
        
        # 记录到历史
        self.action_history.append({
            "step": state.step_index,
            "action": action.action.value,
            "mark_id": action.mark_id,
            "target_text": action.target_text,
            "thinking": action.thinking,
            "page_url": page_url,
            "loop_detected": loop_detected,
        })
        
        # 保存截图到历史（用于下次决策时发送给 LLM）
        self._save_screenshot_to_history(
            step=state.step_index,
            screenshot_base64=screenshot_base64,
            action=action.action.value,
            page_url=page_url,
        )
        
        return action
    
    def _save_screenshot_to_history(
        self, 
        step: int, 
        screenshot_base64: str, 
        action: str, 
        page_url: str
    ) -> None:
        """保存截图到历史记录"""
        self.screenshot_history.append({
            "step": step,
            "screenshot_base64": screenshot_base64,
            "action": action,
            "page_url": page_url,
        })
        
        # 只保留最近 N 张截图
        max_history = self.history_screenshots + 1  # 多保留一张以防万一
        if len(self.screenshot_history) > max_history:
            self.screenshot_history = self.screenshot_history[-max_history:]
    
    def _build_multimodal_content(
        self, 
        text_content: str, 
        current_screenshot: str, 
        current_step: int
    ) -> list:
        """
        构建包含历史截图的多模态消息内容
        
        返回格式: [text, image1, text1, image2, text2, ..., current_image]
        """
        content = []
        
        # 1. 添加文本内容
        content.append({
            "type": "text",
            "text": text_content,
        })
        
        # 2. 添加历史截图（如果有的话）
        # 获取最近的 N-1 张历史截图（不包括当前这一步）
        history_to_show = self.screenshot_history[-(self.history_screenshots - 1):] if self.screenshot_history else []
        
        if history_to_show:
            content.append({
                "type": "text",
                "text": "\n---\n## 📸 历史截图（帮助你理解之前的操作）\n",
            })
            
            for i, hist in enumerate(history_to_show):
                # 添加截图说明
                content.append({
                    "type": "text",
                    "text": f"### 步骤 {hist['step'] + 1} 的截图（执行了 {hist['action']}）：",
                })
                # 添加截图（使用 low detail 节省 token）
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{hist['screenshot_base64']}",
                        "detail": "low",  # 历史截图用低分辨率
                    },
                })
        
        # 3. 添加当前截图说明和截图
        content.append({
            "type": "text",
            "text": f"\n---\n## 📸 当前截图（步骤 {current_step + 1}，请基于此截图做决策）：",
        })
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{current_screenshot}",
                "detail": "high",  # 当前截图用高分辨率
            },
        })
        
        return content
    
    def _detect_loop(self) -> bool:
        """检测是否存在循环操作模式"""
        if len(self.recent_action_signatures) < 4:
            return False
        
        # 检测长度为 2 的循环（A-B-A-B）
        sigs = self.recent_action_signatures
        if len(sigs) >= 4:
            if sigs[-1] == sigs[-3] and sigs[-2] == sigs[-4]:
                return True
        
        # 检测长度为 3 的循环（A-B-C-A-B-C）
        if len(sigs) >= 6:
            if sigs[-1] == sigs[-4] and sigs[-2] == sigs[-5] and sigs[-3] == sigs[-6]:
                return True
        
        # 检测连续相同操作
        if len(sigs) >= 3 and sigs[-1] == sigs[-2] == sigs[-3]:
            return True
        
        return False
    
    def is_page_fully_scrolled(self, page_url: str) -> bool:
        """检查页面是否已被完整滚动过"""
        if page_url in self.page_scroll_history:
            return self.page_scroll_history[page_url].get("fully_scrolled", False)
        return False
    
    def get_page_scroll_status(self, page_url: str) -> str:
        """获取页面滚动状态描述"""
        if page_url not in self.page_scroll_history:
            return "未滚动"
        
        history = self.page_scroll_history[page_url]
        if history.get("fully_scrolled"):
            return "✅ 已完整滚动（从顶到底再回顶）"
        elif history.get("reached_bottom"):
            return "⚠️ 已滚动到底部（但未滚回顶部）"
        else:
            directions = history.get("scroll_directions", [])
            if directions:
                return f"部分滚动（方向: {', '.join(directions[-5:])}）"
            return "未滚动"

    def _build_user_message(
        self,
        state: "AgentState",
        marks_text: str,
        target_found_in_page: bool = False,
        scroll_info: ScrollInfo | None = None,
    ) -> str:
        """构建用户消息（包含历史记录）"""
        parts = []

        # 任务计划（如果有）
        if self.task_plan:
            parts.append(f"## 任务计划\n{self.task_plan}")

        # 任务信息
        parts.append(f"## 任务目标\n{state.input.task}")
        parts.append(f"## 提取目标\n精确匹配文本「{state.input.target_text}」")
        
        # 目标文本是否已在页面中找到
        if target_found_in_page:
            parts.append(f"## ⚠️ 重要提示\n页面中已发现目标文本「{state.input.target_text}」！请立即使用 extract 动作提取包含该文本的元素，然后使用 done 结束任务。")

        # 循环检测警告
        if self._detect_loop():
            parts.append(f"## 🚨 严重警告：检测到循环操作！\n你正在重复之前的操作序列！请立即改变策略：\n- 如果在找目标，尝试使用 go_back 返回上一页\n- 如果已经尝试多个项目都没找到，使用 done 结束任务\n- 不要再重复相同的点击或滚动！")

        # 滚动次数警告
        if self.scroll_count >= self.max_consecutive_scrolls - 1:
            parts.append(f"## ⚠️ 滚动警告\n你已经连续滚动了 {self.scroll_count} 次！请停止滚动，尝试其他操作（如点击链接、输入搜索等）。如果确实找不到目标，请使用 go_back 返回或 done 结束任务。")
        elif self.scroll_count >= 3:
            parts.append(f"## ⚠️ 注意\n已连续滚动 {self.scroll_count} 次。如果目标不在当前页面，考虑其他方式查找。")

        # 页面滚动历史（关键！告诉 LLM 这个页面是否已经完整滚动过）
        page_url = state.page_url
        page_scroll_status = self.get_page_scroll_status(page_url)
        is_fully_scrolled = self.is_page_fully_scrolled(page_url)
        
        if is_fully_scrolled:
            parts.append(f"## 🔴 重要：当前页面已完整滚动过！\n此页面你已经从头滚到尾又滚回来了，**不要再滚动这个页面**！\n- 如果没找到目标，说明目标不在这个页面\n- 请点击其他链接进入新页面，或使用 go_back 返回")

        # 页面滚动状态
        if scroll_info:
            scroll_status = f"## 页面滚动状态\n"
            scroll_status += f"- 本页滚动历史: {page_scroll_status}\n"
            scroll_status += f"- 滚动进度: {scroll_info.scroll_percent}%\n"
            if scroll_info.is_at_top:
                scroll_status += f"- 📍 当前位置: 页面顶部\n"
            elif scroll_info.is_at_bottom:
                scroll_status += f"- 📍 当前位置: **页面底部**（无法继续向下滚动！）\n"
            else:
                scroll_status += f"- 📍 当前位置: 页面中部\n"
            scroll_status += f"- 可向下滚动: {'是' if scroll_info.can_scroll_down else '否（已到底部）'}\n"
            scroll_status += f"- 可向上滚动: {'是' if scroll_info.can_scroll_up else '否（已在顶部）'}"
            parts.append(scroll_status)

        # 当前状态
        parts.append(f"## 当前页面\n- URL: {state.page_url}\n- 标题: {state.page_title}")
        parts.append(f"## 当前步骤\n第 {state.step_index + 1} 步（最多 {state.input.max_steps} 步）")

        # 历史操作记录（改进格式，更清晰）
        if self.action_history:
            history_lines = ["## 历史操作记录（⚠️ 不要重复这些操作！）"]
            
            # 按页面分组显示历史
            current_page_actions = []
            other_page_actions = []
            
            for h in self.action_history[-15:]:
                action_desc = f"步骤{h['step']+1}: {h['action']}"
                if h.get('mark_id'):
                    action_desc += f" [元素{h['mark_id']}]"
                if h.get('target_text'):
                    action_desc += f" \"{h['target_text'][:15]}...\""
                
                if h.get('page_url') == page_url:
                    current_page_actions.append(action_desc)
                else:
                    other_page_actions.append(action_desc)
            
            if current_page_actions:
                history_lines.append("### 在当前页面的操作（不要重复！）：")
                for a in current_page_actions:
                    history_lines.append(f"  - {a}")
            
            if other_page_actions:
                history_lines.append("### 在其他页面的操作：")
                for a in other_page_actions[-5:]:  # 只显示最近 5 个
                    history_lines.append(f"  - {a}")
            
            parts.append("\n".join(history_lines))

        # 上一步结果
        if state.last_action and state.last_result:
            last_info = f"## 上一步操作\n"
            last_info += f"- 动作: {state.last_action.action.value}\n"
            if state.last_action.mark_id:
                last_info += f"- 目标: 编号 {state.last_action.mark_id}\n"
            last_info += f"- 结果: {'成功' if state.last_result.success else '失败'}\n"
            if state.last_result.error:
                last_info += f"- 错误: {state.last_result.error}\n"
            if state.last_result.extracted_text:
                last_info += f"- 提取内容: {state.last_result.extracted_text[:200]}\n"
            parts.append(last_info)

        # 元素列表
        parts.append(f"## 可交互元素列表\n{marks_text}")

        # 提示
        parts.append("## 请分析截图并决定下一步操作\n以 JSON 格式输出你的决策。注意不要重复之前已执行的操作！")

        return "\n\n".join(parts)

    def _parse_response(self, response_text: str) -> Action:
        """解析 LLM 响应"""
        # 先清理 markdown 代码块标记
        cleaned_text = response_text
        
        # 移除 ```json ... ``` 或 ``` ... ``` 包裹
        code_block_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', cleaned_text)
        if code_block_match:
            cleaned_text = code_block_match.group(1).strip()
        
        # 尝试提取 JSON 对象
        json_match = re.search(r'\{[\s\S]*\}', cleaned_text)
        if not json_match:
            # 如果没有找到 JSON，返回 retry
            return Action(
                action=ActionType.RETRY,
                thinking=f"无法解析 LLM 响应: {response_text[:200]}",
            )

        try:
            json_str = json_match.group()
            # 尝试修复常见的 JSON 问题（如末尾多余逗号）
            json_str = re.sub(r',\s*}', '}', json_str)
            json_str = re.sub(r',\s*]', ']', json_str)
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            return Action(
                action=ActionType.RETRY,
                thinking=f"JSON 解析失败 ({str(e)}): {response_text[:200]}",
            )

        # 解析 action 类型
        action_str = data.get("action", "retry").lower()
        try:
            action_type = ActionType(action_str)
        except ValueError:
            action_type = ActionType.RETRY

        # 解析 scroll_delta
        scroll_delta = None
        if "scroll_delta" in data:
            sd = data["scroll_delta"]
            if isinstance(sd, list) and len(sd) == 2:
                scroll_delta = (int(sd[0]), int(sd[1]))

        return Action(
            action=action_type,
            mark_id=data.get("mark_id"),
            target_text=data.get("target_text"),
            text=data.get("text"),
            key=data.get("key"),
            scroll_delta=scroll_delta,
            thinking=data.get("thinking", ""),
            expectation=data.get("expectation"),
        )
