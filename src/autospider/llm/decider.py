"""多模态 LLM 决策器"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from ..config import config
from ..types import Action, ActionType

if TYPE_CHECKING:
    from ..types import AgentState, SoMSnapshot


# ============================================================================
# 系统提示词
# ============================================================================

SYSTEM_PROMPT = """你是网页自动化Agent。分析截图中标注了红色边框和数字编号的可交互元素，决定下一步操作。

## 动作类型
- click: 点击元素 (需要mark_id)
- type: 输入文本 (需要mark_id和text)
- press: 按键 (需要key，如Enter)
- scroll: 滚动 (需要scroll_delta，如[0,300]向下)
- extract: 提取文本 (需要mark_id)
- done: 任务完成
- retry: 重试

## 输出格式 (严格JSON，不要markdown代码块)
{"thinking":"简短思考","action":"click","mark_id":1,"target_text":"按钮文字"}

## 规则
1. 一次只做一个操作
2. 优先使用截图中的数字编号
3. thinking要简短（50字内）
4. 找到目标内容后用extract提取，再用done结束

## ⚠️ 重要：避免重复操作
1. **仔细检查历史操作**：如果某个元素在历史中已经被点击过，且没有找到目标，**不要再次点击它**
2. 如果被告知某些操作被禁止，你**必须**选择其他不同的操作
3. 陷入循环时，尝试：点击其他Tab/按钮、查看附件或相关链接
4. 避免在同一页面上反复点击相同的元素

## ⚠️ 滚动限制
1. 如果历史显示已连续滚动多次，**停止滚动**，尝试点击其他元素（如Tab、附件、链接）
2. 如果被告知"scroll_blocked"或"页面已到底"，**禁止再滚动**，必须选择其他操作
3. 如果页面已探索完毕但未找到目标，检查是否有其他Tab或链接可以点击
4. 若确认目标内容不存在于当前页面，使用done结束并说明情况"""


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

    async def decide(
        self,
        state: "AgentState",
        screenshot_base64: str,
        marks_text: str,
        action_history: list[dict] | None = None,
        blocked_actions: list[str] | None = None,
    ) -> Action:
        """
        根据当前状态和截图决定下一步操作
        
        Args:
            state: Agent 状态
            screenshot_base64: 带 SoM 标注的截图（Base64）
            marks_text: 格式化的 marks 文本描述
            action_history: 历史操作记录列表
            blocked_actions: 被禁止的操作签名列表
        
        Returns:
            下一步操作
        """
        # 构建用户消息
        user_content = self._build_user_message(
            state, 
            marks_text,
            action_history=action_history or [],
            blocked_actions=blocked_actions or [],
        )

        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(
                content=[
                    {
                        "type": "text",
                        "text": user_content,
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{screenshot_base64}",
                            "detail": "high",
                        },
                    },
                ]
            ),
        ]

        # 调用 LLM
        response = await self.llm.ainvoke(messages)
        response_text = response.content

        # 解析响应
        action = self._parse_response(response_text)
        return action

    def _build_user_message(
        self, 
        state: "AgentState", 
        marks_text: str,
        action_history: list[dict] | None = None,
        blocked_actions: list[str] | None = None,
    ) -> str:
        """构建用户消息"""
        parts = []

        # 任务信息
        parts.append(f"## 任务目标\n{state.input.task}")
        parts.append(f"## 提取目标\n找到并提取包含「{state.input.target_text}」的内容")

        # 当前状态
        parts.append(f"## 当前页面\n- URL: {state.page_url}\n- 标题: {state.page_title}")
        parts.append(f"## 当前步骤\n第 {state.step_index + 1} 步（最多 {state.input.max_steps} 步）")

        # 历史操作记录（滑动窗口，最近 8 步）
        if action_history:
            recent_history = action_history[-8:]
            history_lines = ["## 📜 最近操作历史（请仔细检查，避免重复！）"]
            for h in recent_history:
                step = h.get("step", "?")
                action = h.get("action", "?")
                target = h.get("target_text", "")
                mark_id = h.get("mark_id", "")
                success = "✓" if h.get("success") else "✗"
                
                if action == "click":
                    history_lines.append(f"- Step {step}: [Click] 「{target or f'编号{mark_id}'}」 {success}")
                elif action == "scroll":
                    history_lines.append(f"- Step {step}: [Scroll] 向下滚动 {success}")
                elif action == "type":
                    history_lines.append(f"- Step {step}: [Type] 输入文本 {success}")
                else:
                    history_lines.append(f"- Step {step}: [{action}] {target} {success}")
            
            parts.append("\n".join(history_lines))
        
        # 禁止操作列表
        if blocked_actions:
            blocked_info = "## 🚫 以下操作已被禁止（死循环检测）\n"
            blocked_info += "**不要再执行这些操作，必须选择其他方式！**\n"
            for sig in blocked_actions[-5:]:  # 最多显示 5 个
                blocked_info += f"- {sig}\n"
            parts.append(blocked_info)

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
        parts.append("## 请分析截图并决定下一步操作\n以 JSON 格式输出你的决策。\n\n**重要提醒**：检查历史记录，不要重复点击已经尝试过的元素！")

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
