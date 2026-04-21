"""LLMDecider 的提示词拼装。"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from autospider.platform.llm.decider_runtime import DeciderRuntimeState
from autospider.platform.shared_kernel.types import ScrollInfo

if TYPE_CHECKING:
    from autospider.platform.shared_kernel.types import AgentState


def build_multimodal_content(
    text_content: str,
    current_screenshot: str,
    current_step: int,
) -> list[dict[str, Any]]:
    return [
        {
            "type": "text",
            "text": text_content,
        },
        {
            "type": "text",
            "text": f"\n---\n## 📸 当前截图（步骤 {current_step + 1}，请基于此截图做决策）：",
        },
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{current_screenshot}",
                "detail": "high",
            },
        },
    ]


def _format_tab_context(tab_context: dict[str, Any] | None) -> str:
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


def build_decider_user_message(
    *,
    runtime_state: DeciderRuntimeState,
    state: "AgentState",
    target_found_in_page: bool,
    scroll_info: ScrollInfo | None,
    tab_context: dict[str, Any] | None,
    page_accessibility_text: str,
    task_plan: str | None,
) -> str:
    parts: list[str] = []
    if task_plan:
        parts.append(f"## 任务计划\n{task_plan}")

    parts.append(f"## 任务目标\n{state.input.task}")
    parts.append(f"## 提取目标\n精确匹配文本「{state.input.target_text}」")

    if target_found_in_page:
        parts.append(
            f"## ⚠️ 重要提示\n页面中已发现目标文本「{state.input.target_text}」！请立即使用 extract 动作提取包含该文本的元素，然后使用 done 结束任务。"
        )

    if runtime_state.detect_loop():
        parts.append(
            "## 🚨 严重警告：检测到循环操作！\n你正在重复之前的操作序列！请立即改变策略：\n- 如果在找目标，尝试使用 go_back 返回上一页\n- 如果当前是新标签页需要返回旧页，使用 go_back_tab\n- 如果已经尝试多个项目都没找到，使用 done 结束任务\n- 不要再无变化重复相同的点击或滚动！"
        )

    if runtime_state.scroll_count >= runtime_state.max_consecutive_scrolls - 1:
        parts.append(
            f"## ⚠️ 滚动警告\n你已经连续滚动了 {runtime_state.scroll_count} 次！请停止滚动，尝试其他操作（如点击链接、输入搜索等）。如果确实找不到目标，请使用 go_back 返回；若在新标签页，使用 go_back_tab；或直接 done 结束任务。"
        )
    elif runtime_state.scroll_count >= 3:
        parts.append(
            f"## ⚠️ 注意\n已连续滚动 {runtime_state.scroll_count} 次。如果目标不在当前页面，考虑其他方式查找。"
        )

    page_url = state.page_url
    page_scroll_status = runtime_state.get_page_scroll_status(page_url)
    if runtime_state.is_page_fully_scrolled(page_url):
        parts.append(
            "## 🔴 重要：当前页面已完整滚动过！\n此页面你已经从头滚到尾又滚回来了，**不要再滚动这个页面**！\n- 如果没找到目标，说明目标不在这个页面\n- 请点击其他链接进入新页面，或使用 go_back 返回；若在新标签页，使用 go_back_tab"
        )

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
        scroll_status += f"- 可向下滚动: {'是' if scroll_info.can_scroll_down else '否（已到底部）'}\n"
        scroll_status += f"- 可向上滚动: {'是' if scroll_info.can_scroll_up else '否（已在顶部）'}"
        parts.append(scroll_status)

    parts.append(f"## 当前页面\n- URL: {state.page_url}\n- 标题: {state.page_title}")
    parts.append(_format_tab_context(tab_context))
    parts.append(f"## 当前步骤\n第 {state.step_index + 1} 步（最多 {state.input.max_steps} 步）")

    if page_accessibility_text:
        parts.append(f"## 页面可见文本（target_text 必须逐字来自此处）\n{page_accessibility_text}")

    if runtime_state.action_history:
        history_lines = ["## 历史操作记录（⚠️ 不要无变化重复这些操作！）"]
        current_page_actions: list[str] = []
        other_page_actions: list[str] = []
        for item in runtime_state.action_history[-15:]:
            action_desc = f"步骤{item['step'] + 1}: {item['action']}"
            if item.get("mark_id"):
                action_desc += f" [元素{item['mark_id']}]"
            if item.get("target_text"):
                action_desc += f" \"{item['target_text'][:15]}...\""
            if item.get("page_url") == page_url:
                current_page_actions.append(action_desc)
            else:
                other_page_actions.append(action_desc)
        if current_page_actions:
            history_lines.append("### 在当前页面的操作（不要无变化重复！）：")
            for action_desc in current_page_actions:
                history_lines.append(f"  - {action_desc}")
        if other_page_actions:
            history_lines.append("### 在其他页面的操作：")
            for action_desc in other_page_actions[-5:]:
                history_lines.append(f"  - {action_desc}")
        parts.append("\n".join(history_lines))

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

    parts.append(
        "## 请分析截图并决定下一步操作\n以 JSON 格式输出你的决策。注意不要无变化重复之前已执行的操作！"
    )
    return "\n\n".join(parts)
