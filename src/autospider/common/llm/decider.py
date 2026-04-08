"""多模态 LLM 决策器"""

from __future__ import annotations

from typing import Any
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from ..config import config
from ..types import Action, ActionType, ScrollInfo
from ..protocol import parse_protocol_message
from ..som.text_first import resolve_single_mark_id
from ..utils.paths import get_prompt_path
from ..utils.prompt_template import render_template
from .streaming import ainvoke_with_stream
from .trace_logger import append_llm_trace

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
        history_screenshots: int = 3,  # 兼容参数：历史截图功能已移除
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
            model_kwargs={"response_format": {"type": "json_object"}},
            extra_body={"enable_thinking": config.llm.enable_thinking},
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

        # 历史截图功能已移除，保留参数仅用于兼容旧调用方
        _ = history_screenshots

    async def decide(
        self,
        state: "AgentState",
        screenshot_base64: str,
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
            target_found_in_page: 页面中是否发现了目标文本
            scroll_info: 页面滚动状态信息

        Returns:
            下一步操作
        """
        tab_context = await self._collect_tab_context(page)
        # 构建用户消息
        user_content = self._build_user_message(
            state,
            target_found_in_page,
            scroll_info,
            tab_context,
        )

        # 构建消息内容（仅包含当前截图）
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
        response = await ainvoke_with_stream(self.llm, messages)
        response_text = response.content

        # 解析响应
        action = self._parse_response(response)
        action = self._normalize_back_action(action, tab_context)

        append_llm_trace(
            component="decider",
            payload={
                "model": self.model,
                "state": {
                    "step_index": state.step_index,
                    "page_url": state.page_url,
                    "page_title": state.page_title,
                    "task": state.input.task,
                    "target_text": state.input.target_text,
                },
                "tab_context": tab_context,
                "input": {
                    "system_prompt": system_prompt,
                    "user_content": user_content,
                    "target_found_in_page": target_found_in_page,
                    "scroll_info": (
                        scroll_info.model_dump() if scroll_info is not None else None
                    ),
                    "screenshot_base64_len": len(screenshot_base64 or ""),
                },
                "output": {
                    "raw_response": str(response_text),
                    "parsed_action": action.model_dump(),
                },
            },
        )

        snapshot_to_use = snapshot or state.current_snapshot
        if (
            snapshot_to_use
            and page is not None
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
                if corrected_mark_id is not None:
                    if corrected_mark_id != action.mark_id:
                        action.mark_id = corrected_mark_id
                    elif action.mark_id is None:
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
        target_found_in_page: bool = False,
        scroll_info: ScrollInfo | None = None,
        tab_context: dict[str, Any] | None = None,
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
        parts.append(self._format_tab_context(tab_context))
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

        # 提示
        parts.append(
            "## 请分析截图并决定下一步操作\n以 JSON 格式输出你的决策。注意不要无变化重复之前已执行的操作！"
        )

        return "\n\n".join(parts)

    async def _collect_tab_context(self, page: "Page" | None) -> dict[str, Any]:
        """收集标签页与回退能力上下文，用于区分 go_back 与 go_back_tab。"""
        context: dict[str, Any] = {
            "available": False,
            "tab_count": 1,
            "current_tab_index": 1,
            "history_length": None,
            "can_go_back": None,
            "tabs_preview": [],
        }
        if page is None:
            return context

        try:
            pages = list(page.context.pages)
            if pages:
                context["tab_count"] = len(pages)

                raw_current = self._unwrap_page(page)
                current_index = 1
                preview: list[str] = []
                for idx, candidate in enumerate(pages, start=1):
                    raw_candidate = self._unwrap_page(candidate)
                    if raw_current is not None and raw_candidate is raw_current:
                        current_index = idx
                    url = getattr(candidate, "url", "") or ""
                    if idx <= 5:
                        preview.append(f"{idx}. {url[:120]}")

                context["current_tab_index"] = current_index
                context["tabs_preview"] = preview
        except Exception:
            pass

        try:
            history_length_raw = await page.evaluate(
                "() => (window.history && window.history.length) ? window.history.length : 1"
            )
            history_length = int(history_length_raw)
            context["history_length"] = history_length
            context["can_go_back"] = history_length > 1
        except Exception:
            context["history_length"] = None
            context["can_go_back"] = None

        context["available"] = True
        return context

    def _format_tab_context(self, tab_context: dict[str, Any] | None) -> str:
        """格式化标签页上下文文本，喂给 LLM。"""
        if not tab_context or not tab_context.get("available"):
            return "## 标签页状态\n- 未获取到标签页信息。"

        tab_count = int(tab_context.get("tab_count") or 1)
        current_idx = int(tab_context.get("current_tab_index") or 1)
        history_length = tab_context.get("history_length")
        can_go_back = tab_context.get("can_go_back")
        tabs_preview = tab_context.get("tabs_preview") or []

        lines = [
            "## 标签页状态",
            f"- 当前标签页序号: {current_idx}/{tab_count}",
            f"- 当前页历史长度: {history_length if history_length is not None else '未知'}",
            (
                f"- 当前页可否 go_back: {'是' if can_go_back else '否'}"
                if can_go_back is not None
                else "- 当前页可否 go_back: 未知"
            ),
        ]
        if tab_count <= 1:
            lines.append("- 强规则: 当前只有 1 个标签页，禁止使用 go_back_tab。")
        else:
            lines.append(
                "- 强规则: 只有在“当前页是新标签页且要关闭回到原标签”时才使用 go_back_tab；"
                "否则优先用 go_back。"
            )
        if tabs_preview:
            lines.append("- 已打开标签页 URL（最多 5 个）:")
            for item in tabs_preview:
                lines.append(f"  - {item}")

        return "\n".join(lines)

    def _normalize_back_action(self, action: Action, tab_context: dict[str, Any]) -> Action:
        """对 go_back / go_back_tab 做安全纠偏，减少模型误判。"""
        tab_count = int(tab_context.get("tab_count") or 1)
        history_length = tab_context.get("history_length")
        can_go_back = tab_context.get("can_go_back")

        if action.action == ActionType.GO_BACK_TAB and tab_count <= 1:
            action.action = ActionType.GO_BACK
            tip = "自动纠偏: 单标签页改为 go_back"
            action.thinking = f"{action.thinking} | {tip}" if action.thinking else tip
            return action

        if (
            action.action == ActionType.GO_BACK
            and tab_count > 1
            and history_length is not None
            and can_go_back is False
        ):
            action.action = ActionType.GO_BACK_TAB
            tip = "自动纠偏: 当前页无历史且多标签页，改为 go_back_tab"
            action.thinking = f"{action.thinking} | {tip}" if action.thinking else tip

        return action

    def _unwrap_page(self, page: Any) -> Any:
        """兼容 GuardedPage 与原生 Page。"""
        unwrap = getattr(page, "unwrap", None)
        if callable(unwrap):
            try:
                return unwrap()
            except Exception:
                return page
        return page

    def _parse_response(self, response_payload: Any) -> Action:
        """解析 LLM 响应"""
        response_text = getattr(response_payload, "content", response_payload)
        response_text_preview = str(response_text)
        message = parse_protocol_message(response_payload)
        if not message:
            return Action(
                action=ActionType.RETRY,
                thinking=f"无法解析 LLM 响应: {response_text_preview[:200]}",
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
            if args.get("text") and (
                args.get("mark_id") is not None or args.get("target_text")
            ):
                action_type = ActionType.TYPE
                inferred = True
            elif args.get("scroll_delta") is not None:
                action_type = ActionType.SCROLL
                inferred = True
            elif args.get("url"):
                action_type = ActionType.NAVIGATE
                inferred = True
            elif args.get("mark_id") is not None or args.get("target_text"):
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

        thinking = message.get("thinking", "") or ""
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
            expectation=args.get("expectation") or args.get("summary"),
            summary=args.get("summary"),
        )
