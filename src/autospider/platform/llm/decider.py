"""多模态 LLM 决策器。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage, SystemMessage

from autospider.platform.browser.som.text_first import resolve_single_mark_id
from autospider.platform.config.runtime import config
from autospider.platform.llm.action_mapping import parse_action_from_response
from autospider.platform.llm.decider_prompt import (
    build_decider_user_message,
    build_multimodal_content,
)
from autospider.platform.llm.decider_runtime import (
    DeciderRuntimeState,
    collect_tab_context,
    normalize_back_action,
)
from autospider.platform.llm.client_factory import (
    build_json_chat_openai,
    build_runtime_json_llm,
)
from autospider.platform.llm.protocol import (
    extract_response_text_from_llm_payload,
    summarize_llm_payload,
)
from autospider.platform.llm.streaming import ainvoke_with_stream
from autospider.platform.llm.trace_logger import append_llm_trace
from autospider.platform.observability.logger import get_logger
from autospider.platform.shared_kernel.types import Action, ActionType, ScrollInfo
from autospider.platform.shared_kernel.utils.paths import get_prompt_path
from autospider.platform.shared_kernel.utils.prompt_template import render_template

if TYPE_CHECKING:
    from playwright.async_api import Page
    from autospider.platform.shared_kernel.types import AgentState, SoMSnapshot

logger = get_logger(__name__)
PROMPT_TEMPLATE_PATH = get_prompt_path("decider.yaml")


class LLMDecider:
    """多模态 LLM 决策器。"""

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        model: str | None = None,
    ):
        if api_key or api_base or model:
            resolved_api_key = api_key or config.llm.api_key
            resolved_api_base = api_base or config.llm.api_base
            resolved_model = model or config.llm.model
            self.api_key = resolved_api_key
            self.api_base = resolved_api_base
            self.model = resolved_model
            self.llm = build_json_chat_openai(
                api_key=resolved_api_key,
                api_base=resolved_api_base,
                model=resolved_model,
                temperature=config.llm.temperature,
                max_tokens=config.llm.max_tokens,
            )
        else:
            resolved = config.llm
            self.api_key = resolved.api_key
            self.api_base = resolved.api_base
            self.model = resolved.model
            self.llm = build_runtime_json_llm(
                prefer_planner=False,
                temperature=resolved.temperature,
                max_tokens=resolved.max_tokens,
            )

        self.task_plan: str | None = None
        self.runtime_state = DeciderRuntimeState()
        self.last_failure_record: dict[str, Any] | None = None

    async def decide(
        self,
        state: "AgentState",
        screenshot_base64: str,
        target_found_in_page: bool = False,
        scroll_info: ScrollInfo | None = None,
        page: "Page" | None = None,
        snapshot: "SoMSnapshot" | None = None,
        page_accessibility_text: str = "",
    ) -> Action:
        tab_context = await collect_tab_context(page)
        user_content = build_decider_user_message(
            runtime_state=self.runtime_state,
            state=state,
            target_found_in_page=target_found_in_page,
            scroll_info=scroll_info,
            tab_context=tab_context,
            page_accessibility_text=page_accessibility_text,
            task_plan=self.task_plan,
        )
        message_content = build_multimodal_content(
            user_content,
            screenshot_base64,
            state.step_index,
        )
        system_prompt = render_template(PROMPT_TEMPLATE_PATH, section="system_prompt")
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=message_content),
        ]

        response = await ainvoke_with_stream(self.llm, messages)
        response_text = extract_response_text_from_llm_payload(response)
        response_summary = summarize_llm_payload(response)
        action = self._parse_response(response)
        action = normalize_back_action(action, tab_context)
        await self._maybe_correct_mark_id(
            action=action,
            page=page,
            snapshot=snapshot or state.current_snapshot,
        )

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
                    "scroll_info": scroll_info.model_dump() if scroll_info is not None else None,
                    "screenshot_base64_len": len(screenshot_base64 or ""),
                },
                "response_summary": response_summary,
                "output": {
                    "raw_response": str(response_text),
                    "parsed_action": action.model_dump(),
                    "failure_record": action.failure_record,
                },
            },
        )

        self.runtime_state.record_action(action=action, state=state, scroll_info=scroll_info)
        return action

    async def _maybe_correct_mark_id(
        self,
        *,
        action: Action,
        page: "Page" | None,
        snapshot: "SoMSnapshot" | None,
    ) -> None:
        if (
            snapshot is None
            or page is None
            or not action.target_text
            or action.action not in {ActionType.CLICK, ActionType.TYPE, ActionType.EXTRACT}
        ):
            return
        try:
            corrected_mark_id = await resolve_single_mark_id(
                page=page,
                llm=self.llm,
                snapshot=snapshot,
                mark_id=action.mark_id,
                target_text=action.target_text,
                max_retries=config.url_collector.max_validation_retries,
            )
        except Exception as exc:
            note = f"mark_id 纠正失败: {str(exc)[:80]}"
            action.thinking = f"{action.thinking} | {note}" if action.thinking else note
            return

        if corrected_mark_id is None:
            return
        if corrected_mark_id != action.mark_id or action.mark_id is None:
            action.mark_id = corrected_mark_id
        tip = "mark_id 已按文本纠正"
        action.thinking = f"{action.thinking} | {tip}" if action.thinking else tip

    def _parse_response(self, response_payload: Any) -> Action:
        self.last_failure_record = None
        action = parse_action_from_response(
            component="decider",
            response_payload=response_payload,
        )
        self.last_failure_record = action.failure_record
        return action
