from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from langchain_core.messages import HumanMessage, SystemMessage

from autospider.platform.browser.accessibility import get_accessibility_text
from autospider.platform.config.runtime import config
from autospider.platform.llm.streaming import ainvoke_with_stream
from autospider.platform.llm.trace_logger import append_llm_trace
from autospider.platform.observability.logger import get_logger
from autospider.platform.llm.protocol import (
    extract_response_text_from_llm_payload,
    parse_json_dict_from_llm,
    summarize_llm_payload,
)
from autospider.platform.shared_kernel.utils.paths import get_prompt_path
from autospider.platform.shared_kernel.utils.prompt_template import render_template
from autospider.contexts.planning.domain import ExecutionBrief, SubTask

if TYPE_CHECKING:
    from playwright.async_api import Page

    from autospider.contexts.planning.domain import PlannerIntent

logger = get_logger(__name__)
PROMPT_TEMPLATE_PATH = get_prompt_path("planner.yaml")


@dataclass
class ResolvedPlannerVariant:
    resolved_url: str
    anchor_url: str
    nav_steps: list[dict] = field(default_factory=list)
    page_state_signature: str = ""
    variant_label: str = ""
    context: dict[str, str] = field(default_factory=dict)
    same_page_variant: bool = False


@dataclass
class RuntimeSubtaskPlanResult:
    page_type: str
    analysis: dict[str, Any]
    children: list[SubTask] = field(default_factory=list)
    collect_task_description: str = ""
    collect_execution_brief: ExecutionBrief = field(default_factory=ExecutionBrief)


class PlannerAnalysisRuntime(Protocol):
    page: "Page"
    llm: Any
    site_url: str
    user_request: str
    planner_intent: "PlannerIntent"
    selected_skills_context: str
    selected_skills: list[dict]
    prior_failures: list[dict[str, Any]]

    def _format_context_path(self, context: dict[str, str] | None) -> str: ...

    def _format_recent_actions(self, nav_steps: list[dict] | None) -> str: ...

    def _build_planner_candidates(self, snapshot: object, max_candidates: int = 30) -> str: ...

    def _post_process_analysis(
        self,
        result: dict,
        snapshot: object,
        *,
        node_context: dict[str, str] | None = None,
    ) -> dict: ...


class PlannerSiteAnalyzer:
    def __init__(self, planner: PlannerAnalysisRuntime) -> None:
        self._planner = planner

    def _append_observation_note(self, result: dict, note: str) -> dict:
        observations = str(result.get("observations") or "").strip()
        result["observations"] = f"{observations}\n{note}".strip() if observations else note
        return result

    def _get_grouping_semantics(self) -> dict[str, Any]:
        return self._planner.planner_intent.model_dump(mode="python")

    def _format_grouping_semantics(self) -> str:
        grouping = self._get_grouping_semantics()
        return "\n".join(
            [
                f"- group_by: {grouping['group_by']}",
                f"- per_group_target_count: {grouping['per_group_target_count']}",
                f"- total_target_count: {grouping['total_target_count']}",
                f"- category_discovery_mode: {grouping['category_discovery_mode']}",
                f"- requested_categories: {grouping['requested_categories'] or []}",
                f"- category_examples: {grouping['category_examples'] or []}",
            ]
        )

    def _format_prior_failures(self, *, limit: int = 5) -> str:
        if not self._planner.prior_failures:
            return "（无）"
        total = len(self._planner.prior_failures)
        recent = (
            self._planner.prior_failures[-limit:]
            if total > limit
            else list(self._planner.prior_failures)
        )
        lines = [self._format_failure_line(record) for record in recent]
        if total > limit:
            lines.append(f"- ...（共 {total} 条失败证据，仅展示最近 {limit} 条）")
        return "\n".join(lines)

    def _format_failure_line(self, record: dict[str, Any]) -> str:
        category = str(record.get("category") or "unknown").strip()
        detail = str(record.get("detail") or "").strip()
        metadata = dict(record.get("metadata") or {})
        subtask_id = str(metadata.get("subtask_id") or record.get("page_id") or "").strip()
        terminal = str(metadata.get("terminal_reason") or "").strip()
        snippet = f"- [{category}] {detail}"
        if subtask_id:
            snippet += f" (subtask={subtask_id})"
        if terminal and terminal != detail:
            snippet += f" reason={terminal}"
        return snippet

    async def _analyze_site_structure(
        self,
        screenshot_base64: str,
        snapshot: object,
        *,
        node_context: dict[str, str] | None = None,
        nav_steps: list[dict] | None = None,
    ) -> dict | None:
        system_prompt = render_template(PROMPT_TEMPLATE_PATH, section="analyze_site_system_prompt")
        accessibility_text = await self._fetch_accessibility_text()
        user_message = self._build_analysis_user_message(
            snapshot=snapshot,
            accessibility_text=accessibility_text,
            node_context=node_context,
            nav_steps=nav_steps,
        )
        messages = self._build_analysis_messages(system_prompt, user_message, screenshot_base64)
        return await self._invoke_analysis(
            messages=messages,
            snapshot=snapshot,
            system_prompt=system_prompt,
            user_message=user_message,
            node_context=node_context,
            nav_steps=nav_steps,
        )

    async def _fetch_accessibility_text(self) -> str:
        try:
            return await get_accessibility_text(self._planner.page)
        except Exception:
            logger.debug("[Planner] 获取 accessibility text 失败，跳过")
            return ""

    def _build_analysis_user_message(
        self,
        *,
        snapshot: object,
        accessibility_text: str,
        node_context: dict[str, str] | None,
        nav_steps: list[dict] | None,
    ) -> str:
        return render_template(
            PROMPT_TEMPLATE_PATH,
            section="analyze_site_user_message",
            variables={
                "user_request": self._planner.user_request,
                "current_url": self._planner.page.url,
                "current_category_path": self._planner._format_context_path(node_context),
                "recent_actions": self._planner._format_recent_actions(nav_steps),
                "candidate_elements": self._planner._build_planner_candidates(snapshot),
                "grouping_semantics": self._format_grouping_semantics(),
                "page_accessibility_text": accessibility_text or "无",
                "selected_skills_context": self._planner.selected_skills_context
                or "当前未选择任何站点 skills。",
                "prior_failure_evidence": self._format_prior_failures(),
            },
        )

    def _build_analysis_messages(
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

    async def _invoke_analysis(
        self,
        *,
        messages: list[SystemMessage | HumanMessage],
        snapshot: object,
        system_prompt: str,
        user_message: str,
        node_context: dict[str, str] | None,
        nav_steps: list[dict] | None,
    ) -> dict | None:
        trace_input = self._build_trace_input(
            snapshot=snapshot,
            system_prompt=system_prompt,
            user_message=user_message,
            node_context=node_context,
            nav_steps=nav_steps,
        )
        try:
            logger.info("[Planner] 调用 LLM 进行多模态视觉分析...")
            response = await ainvoke_with_stream(self._planner.llm, messages)
            response_text = extract_response_text_from_llm_payload(response)
            response_summary = summarize_llm_payload(response)
            result = parse_json_dict_from_llm(response_text)
            self._append_analysis_trace(
                input_payload=trace_input,
                output_payload={"raw_response": response_text, "parsed_payload": result},
                response_summary=response_summary,
            )
            return self._finalize_analysis_result(result, snapshot, node_context=node_context)
        except Exception as exc:
            self._append_analysis_trace(
                input_payload=trace_input,
                output_payload={},
                response_summary={},
                error=exc,
            )
            logger.exception("[Planner] 调用 LLM 分析网站结构时发生异常")
            return None

    def _build_trace_input(
        self,
        *,
        snapshot: object,
        system_prompt: str,
        user_message: str,
        node_context: dict[str, str] | None,
        nav_steps: list[dict] | None,
    ) -> dict[str, Any]:
        return {
            "system_prompt": system_prompt,
            "user_message": user_message,
            "current_url": self._planner.page.url,
            "site_url": self._planner.site_url,
            "user_request": self._planner.user_request,
            "node_context": dict(node_context or {}),
            "nav_steps": list(nav_steps or []),
            "candidate_count": len(getattr(snapshot, "marks", []) or []),
            "grouping_semantics": self._get_grouping_semantics(),
            "selected_skills": list(self._planner.selected_skills or []),
        }

    def _append_analysis_trace(
        self,
        *,
        input_payload: dict[str, Any],
        output_payload: dict[str, Any],
        response_summary: dict[str, Any],
        error: Exception | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "model": self._resolve_planner_model_name(),
            "input": input_payload,
            "output": output_payload,
            "response_summary": response_summary,
        }
        if error is not None:
            payload["error"] = {"type": type(error).__name__, "message": str(error)}
        append_llm_trace(component="planner_site_analysis", payload=payload)

    def _resolve_planner_model_name(self) -> str | None:
        return (
            getattr(self._planner.llm, "model_name", None)
            or getattr(self._planner.llm, "model", None)
            or config.llm.planner_model
            or config.llm.model
        )

    def _finalize_analysis_result(
        self,
        result: dict | None,
        snapshot: object,
        *,
        node_context: dict[str, str] | None,
    ) -> dict | None:
        if result:
            resolved = self._planner._post_process_analysis(
                result,
                snapshot,
                node_context=node_context,
            )
            subtask_count = len(resolved.get("subtasks", []))
            logger.info("[Planner] LLM 识别到 %d 个候选分类", subtask_count)
            return resolved
        logger.warning("[Planner] LLM 响应内容不符合预期的 JSON 格式")
        return None
