"""LLMDecider 运行时状态与标签页辅助。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from autospider.platform.observability.logger import get_logger
from autospider.platform.shared_kernel.types import Action, ActionType, ScrollInfo

if TYPE_CHECKING:
    from playwright.async_api import Page
    from autospider.platform.shared_kernel.types import AgentState

logger = get_logger(__name__)
MAX_TAB_PREVIEW = 5


class DeciderRuntimeState:
    def __init__(self) -> None:
        self.action_history: list[dict[str, Any]] = []
        self.scroll_count = 0
        self.max_consecutive_scrolls = 5
        self.page_scroll_history: dict[str, dict[str, Any]] = {}
        self.current_page_url = ""
        self.recent_action_signatures: list[str] = []
        self.max_signature_history = 10

    def detect_loop(self) -> bool:
        if len(self.recent_action_signatures) < 4:
            return False

        signatures = self.recent_action_signatures
        if signatures[-1] == signatures[-3] and signatures[-2] == signatures[-4]:
            return True
        if len(signatures) >= 6:
            if (
                signatures[-1] == signatures[-4]
                and signatures[-2] == signatures[-5]
                and signatures[-3] == signatures[-6]
            ):
                return True
        return len(signatures) >= 3 and signatures[-1] == signatures[-2] == signatures[-3]

    def is_page_fully_scrolled(self, page_url: str) -> bool:
        history = self.page_scroll_history.get(page_url)
        return bool(history and history.get("fully_scrolled"))

    def get_page_scroll_status(self, page_url: str) -> str:
        history = self.page_scroll_history.get(page_url)
        if not history:
            return "未滚动"
        if history.get("fully_scrolled"):
            return "✅ 已完整滚动（从顶到底再回顶）"
        if history.get("reached_bottom"):
            return "⚠️ 已滚动到底部（但未滚回顶部）"
        directions = list(history.get("scroll_directions") or [])
        if directions:
            return f"部分滚动（方向: {', '.join(directions[-5:])}）"
        return "未滚动"

    def record_action(
        self,
        *,
        action: Action,
        state: "AgentState",
        scroll_info: ScrollInfo | None,
    ) -> bool:
        page_url = state.page_url
        if page_url != self.current_page_url:
            self.current_page_url = page_url
            self.scroll_count = 0

        if action.action == ActionType.SCROLL:
            self.scroll_count += 1
            history = self.page_scroll_history.setdefault(
                page_url,
                {
                    "fully_scrolled": False,
                    "reached_bottom": False,
                    "reached_top_after_bottom": False,
                    "scroll_directions": [],
                },
            )
            if action.scroll_delta:
                direction = "down" if action.scroll_delta[1] > 0 else "up"
                history["scroll_directions"].append(direction)
            if self.scroll_count >= self.max_consecutive_scrolls:
                logger.info("[Decide] 警告: 已连续滚动 %s 次，可能需要其他操作", self.scroll_count)
        else:
            self.scroll_count = 0

        if scroll_info and page_url in self.page_scroll_history:
            history = self.page_scroll_history[page_url]
            if scroll_info.is_at_bottom:
                history["reached_bottom"] = True
            if history["reached_bottom"] and scroll_info.is_at_top:
                history["reached_top_after_bottom"] = True
                history["fully_scrolled"] = True
                logger.info("[Decide] 📜 页面已完整滚动: %s...", page_url[:50])

        action_signature = f"{action.action.value}:{action.mark_id}:{action.target_text}"
        self.recent_action_signatures.append(action_signature)
        if len(self.recent_action_signatures) > self.max_signature_history:
            self.recent_action_signatures.pop(0)

        loop_detected = self.detect_loop()
        if loop_detected:
            logger.info("[Decide] ⚠️ 检测到循环操作模式！")

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
        return loop_detected


def _unwrap_page(page: Any) -> Any:
    unwrap = getattr(page, "unwrap", None)
    if callable(unwrap):
        try:
            return unwrap()
        except Exception:
            return page
    return page


async def collect_tab_context(page: "Page" | None) -> dict[str, Any]:
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
            raw_current = _unwrap_page(page)
            current_index = 1
            preview: list[str] = []
            for idx, candidate in enumerate(pages, start=1):
                raw_candidate = _unwrap_page(candidate)
                if raw_current is not None and raw_candidate is raw_current:
                    current_index = idx
                url = getattr(candidate, "url", "") or ""
                if idx <= MAX_TAB_PREVIEW:
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


def normalize_back_action(action: Action, tab_context: dict[str, Any]) -> Action:
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
