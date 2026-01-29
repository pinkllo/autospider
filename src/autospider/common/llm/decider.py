"""多模态 LLM 决策器"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from ..config import config
from ..types import Action, ActionType, ScrollInfo
from ..protocol import parse_protocol_message
from ..som.text_first import resolve_single_mark_id
from ..utils.paths import get_prompt_path
from common.utils.prompt_template import render_template

if TYPE_CHECKING:
    from playwright.async_api import Page
    from ..types import AgentState, SoMSnapshot
from autospider.common.logger import get_logger

logger = get_logger(__name__)



# ============================================================================
# Prompt 模板文件路径
# ============================================================================

PROMPT_TEMPLATE_PATH = get_prompt_path("decider.yaml")


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
        history_screenshots: int = 3,  # 保留参数以兼容调用方（不再发送历史截图）
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

        # 历史截图功能已移除，保留字段仅用于兼容历史参数
        self.history_screenshots: int = history_screenshots
        self.screenshot_history: list[dict] = []

    async def decide(
        self,
        state: "AgentState",
        screenshot_base64: str,
        marks_text: str,
        target_found_in_page: bool = False,
        scroll_info: ScrollInfo | None = None,
        page: "Page" | None = None,
        snapshot: "SoMSnapshot" | None = None,
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
        user_content = self._build_user_message(
            state, marks_text, target_found_in_page, scroll_info
        )

        # 构建消息内容（包含历史截图 + 当前截图）
        message_content = self._build_multimodal_content(
            user_content, screenshot_base64, state.step_index
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

        snapshot_to_use = snapshot or state.current_snapshot
        if (
            snapshot_to_use
            and page is not None
            and action.mark_id is not None
            and action.target_text
            and action.action
            in {
                ActionType.CLICK,
                ActionType.TYPE,
                ActionType.EXTRACT,
            }
        ):
            try:
                corrected_mark_id = await resolve_single_mark_id(
                    page=page,
                    llm=self.llm,
                    snapshot=snapshot_to_use,
                    mark_id=action.mark_id,
                    target_text=action.target_text,
                    max_retries=config.url_collector.max_validation_retries,
                )
                if corrected_mark_id is not None and corrected_mark_id != action.mark_id:
                    action.mark_id = corrected_mark_id
                    if action.thinking:
                        action.thinking = f"{action.thinking} | mark_id 已按文本纠正"
                    else:
                        action.thinking = "mark_id 已按文本纠正"
            except Exception as e:
                note = f"mark_id 纠正失败: {str(e)[:80]}"
                if action.thinking:
                    action.thinking = f"{action.thinking} | {note}"
                else:
                    action.thinking = note

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
                logger.info(f"[Decide] 警告: 已连续滚动 {self.scroll_count} 次，可能需要其他操作")
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
                logger.info(f"[Decide] 📜 页面已完整滚动: {page_url[:50]}...")

        # 生成操作签名用于循环检测
        action_sig = f"{action.action.value}:{action.mark_id}:{action.target_text}"
        self.recent_action_signatures.append(action_sig)
        if len(self.recent_action_signatures) > self.max_signature_history:
            self.recent_action_signatures.pop(0)

        # 检测循环模式
        loop_detected = self._detect_loop()
        if loop_detected:
            logger.info("[Decide] ⚠️ 检测到循环操作模式！")

        # 记录到历史
        self.action_history.append(
            {
                "step": state.step_index,
                "action": action.action.value,
                "mark_id": action.mark_id,
                "target_text": action.target_text,
                "thinking": action.thinking,
                "page_url": page_url,
                "loop_detected": loop_detected,
            }
        )

        return action

    def _save_screenshot_to_history(
        self, step: int, screenshot_base64: str, action: str, page_url: str
    ) -> None:
        """保存截图到历史记录"""
        self.screenshot_history.append(
            {
                "step": step,
                "screenshot_base64": screenshot_base64,
                "action": action,
                "page_url": page_url,
            }
        )

        # 只保留最近 N 张截图
        max_history = self.history_screenshots + 1  # 多保留一张以防万一
        if len(self.screenshot_history) > max_history:
            self.screenshot_history = self.screenshot_history[-max_history:]

    def _build_multimodal_content(
        self, text_content: str, current_screenshot: str, current_step: int
    ) -> list:
        """
        构建多模态消息内容（仅发送当前截图）

        返回格式: [text, current_image]
        """
        content = []

        # 1. 添加文本内容
        content.append(
            {
                "type": "text",
                "text": text_content,
            }
        )

        # 2. 添加当前截图说明和截图
        content.append(
            {
                "type": "text",
                "text": f"\n---\n## 📸 当前截图（步骤 {current_step + 1}，请基于此截图做决策）：",
            }
        )
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{current_screenshot}",
                    "detail": "high",  # 当前截图用高分辨率
                },
            }
        )

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
            parts.append(
                f"## ⚠️ 重要提示\n页面中已发现目标文本「{state.input.target_text}」！请立即使用 extract 动作提取包含该文本的元素，然后使用 done 结束任务。"
            )

        # 循环检测警告
        if self._detect_loop():
            parts.append(
                "## 🚨 严重警告：检测到循环操作！\n你正在重复之前的操作序列！请立即改变策略：\n- 如果在找目标，尝试使用 go_back 返回上一页\n- 如果当前是新标签页需要返回旧页，使用 go_back_tab\n- 如果已经尝试多个项目都没找到，使用 done 结束任务\n- 不要再无变化重复相同的点击或滚动！"
            )

        # 滚动次数警告
        if self.scroll_count >= self.max_consecutive_scrolls - 1:
            parts.append(
                f"## ⚠️ 滚动警告\n你已经连续滚动了 {self.scroll_count} 次！请停止滚动，尝试其他操作（如点击链接、输入搜索等）。如果确实找不到目标，请使用 go_back 返回；若在新标签页，使用 go_back_tab；或直接 done 结束任务。"
            )
        elif self.scroll_count >= 3:
            parts.append(
                f"## ⚠️ 注意\n已连续滚动 {self.scroll_count} 次。如果目标不在当前页面，考虑其他方式查找。"
            )

        # 页面滚动历史（关键！告诉 LLM 这个页面是否已经完整滚动过）
        page_url = state.page_url
        page_scroll_status = self.get_page_scroll_status(page_url)
        is_fully_scrolled = self.is_page_fully_scrolled(page_url)

        if is_fully_scrolled:
            parts.append(
                "## 🔴 重要：当前页面已完整滚动过！\n此页面你已经从头滚到尾又滚回来了，**不要再滚动这个页面**！\n- 如果没找到目标，说明目标不在这个页面\n- 请点击其他链接进入新页面，或使用 go_back 返回；若在新标签页，使用 go_back_tab"
            )

        # 页面滚动状态
        if scroll_info:
            scroll_status = "## 页面滚动状态\n"
            scroll_status += f"- 本页滚动历史: {page_scroll_status}\n"
            scroll_status += f"- 滚动进度: {scroll_info.scroll_percent}%\n"
            if scroll_info.is_at_top:
                scroll_status += "- 📍 当前位置: 页面顶部\n"
            elif scroll_info.is_at_bottom:
                scroll_status += "- 📍 当前位置: **页面底部**（无法继续向下滚动！）\n"
            else:
                scroll_status += "- 📍 当前位置: 页面中部\n"
            scroll_status += (
                f"- 可向下滚动: {'是' if scroll_info.can_scroll_down else '否（已到底部）'}\n"
            )
            scroll_status += (
                f"- 可向上滚动: {'是' if scroll_info.can_scroll_up else '否（已在顶部）'}"
            )
            parts.append(scroll_status)

        # 当前状态
        parts.append(f"## 当前页面\n- URL: {state.page_url}\n- 标题: {state.page_title}")
        parts.append(
            f"## 当前步骤\n第 {state.step_index + 1} 步（最多 {state.input.max_steps} 步）"
        )

        # 历史操作记录（改进格式，更清晰）
        if self.action_history:
            history_lines = ["## 历史操作记录（⚠️ 不要无变化重复这些操作！）"]

            # 按页面分组显示历史
            current_page_actions = []
            other_page_actions = []

            for h in self.action_history[-15:]:
                action_desc = f"步骤{h['step']+1}: {h['action']}"
                if h.get("mark_id"):
                    action_desc += f" [元素{h['mark_id']}]"
                if h.get("target_text"):
                    action_desc += f" \"{h['target_text'][:15]}...\""

                if h.get("page_url") == page_url:
                    current_page_actions.append(action_desc)
                else:
                    other_page_actions.append(action_desc)

            if current_page_actions:
                history_lines.append("### 在当前页面的操作（不要无变化重复！）：")
                for a in current_page_actions:
                    history_lines.append(f"  - {a}")

            if other_page_actions:
                history_lines.append("### 在其他页面的操作：")
                for a in other_page_actions[-5:]:  # 只显示最近 5 个
                    history_lines.append(f"  - {a}")

            parts.append("\n".join(history_lines))

        # 上一步结果
        if state.last_action and state.last_result:
            last_info = "## 上一步操作\n"
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
        parts.append(
            "## 请分析截图并决定下一步操作\n以 JSON 格式输出你的决策。注意不要无变化重复之前已执行的操作！"
        )

        return "\n\n".join(parts)

    def _parse_response(self, response_text: str) -> Action:
        """解析 LLM 响应"""
        message = parse_protocol_message(response_text)
        if not message:
            return Action(
                action=ActionType.RETRY,
                thinking=f"无法解析 LLM 响应: {response_text[:200]}",
            )

        # 解析 action 类型
        action_str_raw = message.get("action") or ""
        action_str = str(action_str_raw).strip().lower()
        action_aliases = {
            # 常见同义/历史动作名
            "scroll_down": "scroll",
            "scroll_up": "scroll",
            "press": "retry",
        }
        action_str = action_aliases.get(action_str, action_str)

        args = message.get("args") if isinstance(message.get("args"), dict) else {}

        action_type: ActionType | None = None
        if action_str:
            try:
                action_type = ActionType(action_str)
            except ValueError:
                action_type = None

        # 修改原因：LLM 偶尔会漏写/写错 action，但其它字段已足够推断具体动作；
        # 为避免被误判为 retry 并陷入循环，这里对缺失/非法 action 做自动推断。
        inferred = False
        if action_type is None:
            if args.get("text") and args.get("mark_id") is not None:
                action_type = ActionType.TYPE
                inferred = True
            elif args.get("scroll_delta") is not None:
                action_type = ActionType.SCROLL
                inferred = True
            elif args.get("url"):
                action_type = ActionType.NAVIGATE
                inferred = True
            elif args.get("mark_id") is not None:
                action_type = ActionType.CLICK
                inferred = True
            else:
                action_type = ActionType.RETRY

        # 解析 scroll_delta
        scroll_delta = None
        if "scroll_delta" in args:
            sd = args["scroll_delta"]
            if isinstance(sd, list) and len(sd) == 2:
                scroll_delta = (int(sd[0]), int(sd[1]))

        thinking = message.get("thinking", "") or args.get("reasoning") or ""
        if inferred and not thinking:
            thinking = f"自动推断动作: {action_type.value}"
        if action_type == ActionType.RETRY and not thinking:
            thinking = "LLM 输出未包含可执行 action，已进入重试"

        # 修改原因：当 action=retry 时，清空 mark_id/target_text，避免上层误以为“重试仍指向同一元素”并造成循环提示噪音。
        mark_id = None if action_type == ActionType.RETRY else args.get("mark_id")
        target_text = None if action_type == ActionType.RETRY else args.get("target_text")

        return Action(
            action=action_type,
            mark_id=mark_id,
            target_text=target_text,
            text=args.get("text"),
            key=args.get("key"),
            url=args.get("url"),
            scroll_delta=scroll_delta,
            timeout_ms=args.get("timeout_ms") or 5000,
            thinking=thinking,
            expectation=args.get("expectation"),
        )
