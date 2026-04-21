"""任务澄清器：将自然语言多轮对话转换为可执行爬取配置。"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from autospider.platform.llm.contracts import validate_task_clarifier_payload
from autospider.platform.llm.client_factory import (
    build_runtime_json_llm,
    resolve_runtime_llm_config,
)
from autospider.platform.llm.protocol import (
    extract_json_dict_from_llm_payload,
    extract_response_text_from_llm_payload,
    summarize_llm_payload,
)
from autospider.platform.shared_kernel.utils.paths import get_prompt_path
from autospider.platform.shared_kernel.utils.prompt_template import render_template
from .streaming import ainvoke_with_stream
from .trace_logger import append_llm_trace
from autospider.platform.observability.logger import get_logger

# 获取日志记录器
logger = get_logger(__name__)

# 获取提示词模板路径
PROMPT_TEMPLATE_PATH = get_prompt_path("task_clarifier.yaml")


class TaskClarifier:
    """基于 LLM 的多轮任务澄清器，负责将模糊的对话转化为清晰的爬虫配置。"""

    def __init__(self):
        """初始化澄清器，读取 LLM 相关的配置参数。"""
        self._llm_config = resolve_runtime_llm_config(prefer_planner=True)
        self.llm = build_runtime_json_llm(
            prefer_planner=True,
            temperature=0.1,
            max_tokens=2048,
        )

    async def clarify(
        self,
        history: list[dict[str, str]],
        *,
        available_skills: list[dict[str, str]] | None = None,
        selected_skills: list[dict[str, str]] | None = None,
        selected_skills_context: str | None = None,
    ) -> dict[str, Any]:
        """
        基于当前会话历史返回经 contract 校验后的平台级 payload。

        Args:
            history: 对话历史列表。
            available_skills: 当前 URL 可用的 skills metadata，仅用于 trace。
            selected_skills: 本轮被 selector 选中的 skills metadata，仅用于 trace。
            selected_skills_context: 选中的 SKILL.md 正文上下文。
        """
        conversation_history = self._format_history(history)
        selected_context = (
            str(selected_skills_context or "").strip() or "当前未选择任何站点 skills。"
        )

        system_prompt = render_template(PROMPT_TEMPLATE_PATH, section="system_prompt")
        user_prompt = render_template(
            PROMPT_TEMPLATE_PATH,
            section="user_prompt",
            variables={
                "conversation_history": conversation_history,
                "selected_skills_context": selected_context,
            },
        )

        # 调用 LLM 获取响应
        response = await ainvoke_with_stream(
            self.llm,
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ],
        )
        raw_response = extract_response_text_from_llm_payload(response)
        raw_payload = extract_json_dict_from_llm_payload(response) or {}
        response_summary = summarize_llm_payload(response)
        payload, validation_errors = validate_task_clarifier_payload(raw_payload)
        if raw_payload and validation_errors:
            logger.warning(
                "[TaskClarifier] LLM payload validation failed: %s",
                "; ".join(validation_errors),
            )
        append_llm_trace(
            component="task_clarifier",
            payload={
                "model": self._llm_config["model"],
                "input": {
                    "system_prompt": system_prompt,
                    "user_prompt": user_prompt,
                    "conversation_history": conversation_history,
                    "available_skills": available_skills or [],
                    "selected_skills": selected_skills or [],
                    "selected_skill_paths": [
                        str(item.get("path") or "")
                        for item in list(selected_skills or [])
                        if isinstance(item, dict)
                    ],
                    "selected_skills_context": selected_context,
                },
                "output": {
                    "response_summary": response_summary,
                    "raw_response": raw_response,
                    "parsed_payload": raw_payload,
                    "validated_payload": payload,
                    "payload_validation_errors": validation_errors,
                },
                "response_summary": response_summary,
            },
        )
        return dict(payload)

    def _format_history(self, history: list[dict[str, str]]) -> str:
        """将对话历史转换为字符串列表，供 Prompt 使用。保留最近的 20 条记录。"""
        lines: list[str] = []
        for index, message in enumerate(history[-20:], start=1):
            role_name = str(message.get("role") or "").strip().lower()
            role = "用户" if role_name == "user" else "助手"
            content = str(message.get("content") or "").strip()
            lines.append(f"{index}. {role}: {content}")
        return "\n".join(lines) if lines else "（暂无历史）"
