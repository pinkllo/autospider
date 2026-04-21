from __future__ import annotations

import json
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage

from autospider.platform.browser.accessibility import get_accessibility_text
from autospider.contexts.collection.infrastructure.decision_context_format import (
    format_decision_context as _format_decision_context,
)
from autospider.platform.llm.streaming import ainvoke_with_stream
from autospider.platform.llm.trace_logger import append_llm_trace
from autospider.platform.observability.logger import get_logger
from autospider.platform.llm.protocol import (
    extract_response_text_from_llm_payload,
    parse_protocol_message_diagnostics,
    summarize_llm_payload,
)
from autospider.platform.browser.som.text_first import (
    disambiguate_mark_id_by_text as _disambiguate_mark_id_by_text,
)
from autospider.platform.shared_kernel.utils.prompt_template import render_template
from autospider.contexts.collection.infrastructure.adapters._llm_shared import build_trace_payload
from autospider.contexts.planning.domain import format_execution_brief

if TYPE_CHECKING:
    from autospider.platform.shared_kernel.types import ElementMark, SoMSnapshot

logger = get_logger(__name__)


class CollectorDecisionMixin:
    async def ask_for_decision(
        self,
        snapshot: "SoMSnapshot",
        screenshot_base64: str = "",
        validation_feedback: str = "",
    ) -> dict | None:
        current_url = self.page.url
        logger.info("[LLM] 当前页面: %s...", current_url[:80])
        logger.info("[LLM] 可交互元素数量: %s", len(snapshot.marks))
        logger.info("[LLM] 截图大小: %s 字符", len(screenshot_base64))
        if validation_feedback:
            logger.info("[LLM] 包含验证反馈信息（重新选择）")

        system_prompt = render_template(
            self.prompt_template_path, section="ask_llm_decision_system_prompt"
        )
        user_message = await self._build_decision_user_message(current_url, validation_feedback)
        messages = self._build_visual_messages(system_prompt, user_message, screenshot_base64)
        trace_input = self._build_decision_trace_input(
            snapshot=snapshot,
            current_url=current_url,
            user_message=user_message,
            system_prompt=system_prompt,
            screenshot_base64=screenshot_base64,
            validation_feedback=validation_feedback,
        )
        return await self._invoke_protocol_message(
            component="collector_decision",
            log_prefix="[LLM]",
            messages=messages,
            trace_input=trace_input,
        )

    async def _build_decision_user_message(
        self,
        current_url: str,
        validation_feedback: str,
    ) -> str:
        collected_urls_str = (
            "\n".join(f"- {url}" for url in list(self.collected_urls)[:10])
            if self.collected_urls
            else "暂无"
        )
        accessibility_text = ""
        try:
            accessibility_text = await get_accessibility_text(self.page)
        except Exception:
            logger.debug("[LLM] 获取 accessibility text 失败，跳过")
        user_message = render_template(
            self.prompt_template_path,
            section="ask_llm_decision_user_message",
            variables={
                "task_description": self.task_description,
                "current_url": current_url,
                "visited_count": len(self.visited_detail_urls),
                "collected_urls_str": collected_urls_str,
                "execution_brief": format_execution_brief(self.execution_brief),
                "decision_context": _format_decision_context(self.decision_context),
                "page_accessibility_text": accessibility_text or "无",
                "selected_skills_context": self.selected_skills_context
                or "当前未选择任何站点 skills。",
            },
        )
        if validation_feedback:
            user_message += (
                f"\n\n## ⚠️ 上一次元素选择验证失败\n{validation_feedback}"
                "\n\n请优先依据元素文本重新选择；若文本在页面中有多个匹配，请结合页面位置与上下文做区分。"
            )
        return user_message

    def _build_decision_trace_input(
        self,
        *,
        snapshot: "SoMSnapshot",
        current_url: str,
        user_message: str,
        system_prompt: str,
        screenshot_base64: str,
        validation_feedback: str,
    ) -> dict[str, object]:
        return {
            "system_prompt": system_prompt,
            "user_message": user_message,
            "current_url": current_url,
            "list_url": self.list_url,
            "task_description": self.task_description,
            "visited_detail_count": len(self.visited_detail_urls),
            "collected_urls_sample": list(self.collected_urls)[:10],
            "validation_feedback": validation_feedback,
            "selected_skills": list(self.selected_skills or []),
            "decision_context": dict(self.decision_context or {}),
            "screenshot_base64_len": len(screenshot_base64 or ""),
            "candidate_count": len(getattr(snapshot, "marks", []) or []),
        }

    async def _invoke_protocol_message(
        self,
        *,
        component: str,
        log_prefix: str,
        messages: list[SystemMessage | HumanMessage],
        trace_input: dict[str, object],
    ) -> dict | None:
        raw_response = ""
        response_summary: dict[str, object] = {}
        try:
            logger.info("%s 调用视觉 LLM 进行决策...", log_prefix)
            response = await ainvoke_with_stream(self.decider.llm, messages)
            raw_response = extract_response_text_from_llm_payload(response)
            response_summary = summarize_llm_payload(response)
            diagnostics = parse_protocol_message_diagnostics(response)
            message = diagnostics.get("message")
            append_llm_trace(
                component=component,
                payload=build_trace_payload(
                    llm=self.decider.llm,
                    input_payload=trace_input,
                    raw_response=raw_response,
                    response_summary=response_summary,
                    parsed_payload={
                        "message": message,
                        "validation_errors": diagnostics.get("validation_errors") or [],
                    },
                ),
            )
            if isinstance(message, dict):
                return message
            validation_errors = list(diagnostics.get("validation_errors") or [])
            logger.warning(
                "%s 协议解析失败: %s | response=%s",
                log_prefix,
                "; ".join(validation_errors[:2]) or "unknown_protocol_error",
                raw_response[:200],
            )
        except json.JSONDecodeError as exc:
            logger.warning("%s JSON 解析失败: %s", log_prefix, exc)
            self._append_trace_error(component, trace_input, raw_response, response_summary, exc)
        except Exception as exc:
            self._append_trace_error(component, trace_input, raw_response, response_summary, exc)
            logger.exception("%s 决策失败", log_prefix)
        return None

    def _append_trace_error(
        self,
        component: str,
        trace_input: dict[str, object],
        raw_response: str,
        response_summary: dict[str, object],
        error: Exception,
    ) -> None:
        append_llm_trace(
            component=component,
            payload=build_trace_payload(
                llm=self.decider.llm,
                input_payload=trace_input,
                raw_response=raw_response,
                response_summary=response_summary,
                error=error,
            ),
        )

    def _build_visual_messages(
        self,
        system_prompt: str,
        user_message: str,
        screenshot_base64: str,
    ) -> list[SystemMessage | HumanMessage]:
        return [
            SystemMessage(content=system_prompt),
            HumanMessage(
                content=[
                    {"type": "text", "text": user_message},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{screenshot_base64}"},
                    },
                ]
            ),
        ]

    async def disambiguate_mark_id_by_text(
        self,
        candidates: list["ElementMark"],
        target_text: str,
        max_retries: int = 1,
    ) -> int | None:
        return await _disambiguate_mark_id_by_text(
            page=self.page,
            llm=self.decider.llm,
            candidates=candidates,
            target_text=target_text,
            max_retries=max_retries,
        )
