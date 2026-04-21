from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from autospider.platform.llm.streaming import ainvoke_with_stream
from autospider.platform.llm.trace_logger import append_llm_trace
from autospider.platform.observability.logger import get_logger
from autospider.platform.llm.protocol import (
    extract_response_text_from_llm_payload,
    parse_protocol_message_diagnostics,
    summarize_llm_payload,
)
from autospider.platform.shared_kernel.utils.prompt_template import render_template
from autospider.contexts.collection.infrastructure.adapters._llm_shared import build_trace_payload

logger = get_logger(__name__)


class CollectorPaginationMixin:
    async def extract_jump_widget_with_llm(
        self, snapshot: object, screenshot_base64: str
    ) -> dict | None:
        return await self._detect_visual_widget(
            snapshot=snapshot,
            screenshot_base64=screenshot_base64,
            system_section="jump_widget_llm_system_prompt",
            user_section="jump_widget_llm_user_message",
            component="collector_jump_widget_detection",
            log_prefix="[Extract-JumpWidget-LLM]",
        )

    async def extract_pagination_with_llm(
        self, snapshot: object, screenshot_base64: str
    ) -> dict | None:
        return await self._detect_visual_widget(
            snapshot=snapshot,
            screenshot_base64=screenshot_base64,
            system_section="pagination_llm_system_prompt",
            user_section="pagination_llm_user_message",
            component="collector_pagination_detection",
            log_prefix="[Extract-Pagination-LLM]",
        )

    async def _detect_visual_widget(
        self,
        *,
        snapshot: object,
        screenshot_base64: str,
        system_section: str,
        user_section: str,
        component: str,
        log_prefix: str,
    ) -> dict | None:
        system_prompt = render_template(self.prompt_template_path, section=system_section)
        user_message = render_template(
            self.prompt_template_path,
            section=user_section,
            variables={
                "selected_skills_context": self.selected_skills_context
                or "当前未选择任何站点 skills。",
            },
        )
        messages = [
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
        trace_input = {
            "system_prompt": system_prompt,
            "user_message": user_message,
            "page_url": self.page.url,
            "selected_skills": list(self.selected_skills or []),
            "screenshot_base64_len": len(screenshot_base64 or ""),
            "candidate_count": len(getattr(snapshot, "marks", []) or []),
        }
        raw_response = ""
        response_summary: dict[str, object] = {}
        try:
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
        except Exception as exc:
            append_llm_trace(
                component=component,
                payload=build_trace_payload(
                    llm=self.decider.llm,
                    input_payload=trace_input,
                    raw_response=raw_response,
                    response_summary=response_summary,
                    error=exc,
                ),
            )
            logger.exception("%s LLM 识别失败", log_prefix)
        return None
