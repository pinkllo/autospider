"""任务规划器 (Task Planner) — 负责分析网站结构并将复杂的采集任务拆分为多个子任务。

该模块的核心逻辑是通过 LLM (语言模型) 结合视觉分析 (结合 SoM 标注的截图)，识别目标网站的导航结构
（如菜单、分类列表、频道入口等），并自动生成一系列独立的子任务。
每个子任务通常对应一个特定的分类或频道的列表页。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from ...common.config import config
from ...common.llm.streaming import ainvoke_with_stream
from ...common.llm.trace_logger import append_llm_trace
from ...common.logger import get_logger
from ...common.protocol import (
    extract_response_text_from_llm_payload,
    parse_json_dict_from_llm,
    summarize_llm_payload,
)
from ...common.som import inject_and_scan, capture_screenshot_with_marks, clear_overlay
from ...domain.planning import (
    ExecutionBrief,
    PlanJournalEntry,
    PlanNode,
    PlanNodeType,
    PlannerIntent,
    SubTask,
    SubTaskMode,
    TaskPlan,
)
from ...common.utils.paths import get_prompt_path
from ...common.utils.prompt_template import render_template
from ...graph.control_types import (
    PlanSpec,
    build_default_dispatch_policy,
    build_default_recovery_policy,
)
from ...graph.world_model import build_initial_world_model, upsert_page_model, world_model_to_payload
from ...pipeline.runtime_controls import resolve_concurrency_settings
from .planner_analysis_postprocess import PlannerAnalysisPostProcessMixin
from .planner_artifacts import PlannerArtifacts
from .planner_category_semantics import PlannerCategorySemanticsMixin
from .planner_state import PlannerPageState
from .planner_subtask_builder import PlannerSubtaskBuilderMixin
from .planner_variant_resolver import PlannerVariantResolverMixin

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = get_logger(__name__)
_PLANNER_READY_TIMEOUT_MS = 5000
_PLANNER_READY_FALLBACK_WAIT_MS = 1500

PROMPT_TEMPLATE_PATH = get_prompt_path("planner.yaml")
PLANNER_STAGE = "planning_seeded"
ENTRY_JOURNAL_LIMIT = 3


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


PlannerVariantResolverMixin.ResolvedPlannerVariant = ResolvedPlannerVariant


def _select_entry_node(plan: TaskPlan) -> PlanNode | None:
    if plan.nodes:
        return plan.nodes[0]
    return None


def _resolve_page_type(node: PlanNode) -> str:
    node_type = getattr(node.node_type, "value", str(node.node_type or "")).strip().lower()
    if node_type == PlanNodeType.LEAF.value:
        return PlanNodeType.LIST_PAGE.value
    return node_type or PlanNodeType.CATEGORY.value


def _collect_entry_journal(plan: TaskPlan, node_id: str) -> list[dict[str, Any]]:
    matched = [entry for entry in plan.journal if str(entry.node_id or "") == node_id]
    return [
        {
            "phase": entry.phase,
            "action": entry.action,
            "reason": entry.reason,
            "evidence": entry.evidence,
            "metadata": dict(entry.metadata or {}),
            "created_at": entry.created_at,
        }
        for entry in matched[:ENTRY_JOURNAL_LIMIT]
    ]


def _build_page_metadata(plan: TaskPlan, node: PlanNode) -> dict[str, Any]:
    return {
        "name": node.name,
        "anchor_url": str(node.anchor_url or node.url or ""),
        "page_state_signature": str(node.page_state_signature or ""),
        "variant_label": str(node.variant_label or ""),
        "task_description": node.task_description,
        "observations": node.observations,
        "context": dict(node.context or {}),
        "nav_steps": list(node.nav_steps or []),
        "shared_fields": [dict(field) for field in list(plan.shared_fields or [])],
        "journal_summary": _collect_entry_journal(plan, node.node_id),
    }


def _build_page_models(plan: TaskPlan) -> dict[str, dict[str, Any]]:
    page_models: dict[str, dict[str, Any]] = {}
    fallback_links = max(len(plan.subtasks), 0)
    for node in plan.nodes:
        url = str(node.url or node.anchor_url or plan.site_url or "")
        page_models[node.node_id] = {
            "page_id": node.node_id,
            "url": url,
            "page_type": _resolve_page_type(node),
            "links": int(node.children_count or fallback_links),
            "depth": int(node.depth or 0),
            "metadata": _build_page_metadata(plan, node),
        }
    return page_models


def _resolve_dispatch_policy(request_params: Mapping[str, Any] | None) -> dict[str, Any]:
    default = build_default_dispatch_policy()
    concurrency = resolve_concurrency_settings(dict(request_params or {}))
    max_concurrency = int(concurrency.max_concurrent or default.max_concurrency)
    strategy = "parallel" if max_concurrency > 1 else default.strategy
    return {
        "strategy": strategy,
        "max_concurrency": max_concurrency,
        "reason": "根据规划阶段可执行上下文确定的调度策略",
    }


def _resolve_recovery_policy() -> dict[str, Any]:
    default = build_default_recovery_policy()
    return {
        "max_retries": default.max_retries,
        "fail_fast": default.fail_fast,
        "escalation_categories": list(default.escalation_categories),
        "reason": "使用默认恢复策略等待执行阶段累积失败记录后再调整",
    }


def build_planner_world_payload(
    plan: TaskPlan,
    *,
    request_params: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    world_model = build_initial_world_model(
        request_params=request_params,
        page_models=_build_page_models(plan),
        failure_records=[],
    )
    entry_node = _select_entry_node(plan)
    if entry_node is not None and entry_node.node_id not in world_model.page_models:
        world_model = upsert_page_model(
            world_model,
            page_id=entry_node.node_id,
            url=str(entry_node.url or entry_node.anchor_url or plan.site_url or ""),
            page_type=_resolve_page_type(entry_node),
            links=int(entry_node.children_count or len(plan.subtasks)),
            depth=int(entry_node.depth or 0),
            metadata=_build_page_metadata(plan, entry_node),
        )
    return {
        "request_params": dict(request_params or {}),
        "world_model": world_model_to_payload(world_model),
        "failure_records": [],
    }


def build_planner_control_payload(
    plan: TaskPlan,
    *,
    request_params: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    entry_node = _select_entry_node(plan)
    current_plan = PlanSpec(
        goal=str(getattr(entry_node, "task_description", "") or plan.original_request or ""),
        page_id=str(getattr(entry_node, "node_id", "") or ""),
        stage=PLANNER_STAGE,
        metadata={
            "entry_url": str(getattr(entry_node, "url", "") or plan.site_url or ""),
            "site_url": str(plan.site_url or ""),
            "total_subtasks": int(plan.total_subtasks or len(plan.subtasks)),
        },
    )
    return {
        "current_plan": {
            "goal": current_plan.goal,
            "page_id": current_plan.page_id,
            "stage": current_plan.stage,
            "metadata": dict(current_plan.metadata),
        },
        "dispatch_policy": _resolve_dispatch_policy(request_params),
        "recovery_policy": _resolve_recovery_policy(),
    }


class TaskPlanner(
    PlannerCategorySemanticsMixin,
    PlannerAnalysisPostProcessMixin,
    PlannerSubtaskBuilderMixin,
    PlannerVariantResolverMixin,
):
    """任务规划器：负责将用户的采集请求转化为具体的执行计划。

    主要功能包括：
    1. 导航至目标站点。
    2. 利用 SoM (Set-of-Mark) 技术对页面元素进行标注并截图。
    3. 调用具备视觉能力的 LLM 分析页面结构，识别出符合用户需求的分类入口。
    4. 针对不同类型的网页（静态/SPA），采用多种策略提取分类的实际跳转 URL。
    5. 构建并持久化任务计划 (TaskPlan)，供后续 Worker Agent 执行。
    """

    def __init__(
        self,
        page: "Page",
        site_url: str,
        user_request: str,
        output_dir: str = "output",
        use_main_model: bool = False,
        selected_skills_context: str = "",
        selected_skills: list[dict] | None = None,
        planner_intent: PlannerIntent | dict[str, Any] | None = None,
    ):
        """初始化任务规划器。

        Args:
            page: Playwright 页面实例，用于浏览器交互。
            site_url: 目标网站的根地址或起始 URL。
            user_request: 用户的原始采集需求描述。
            output_dir: 规划结果（TaskPlan）的保存目录，默认为 "output"。
            use_main_model: 是否强制使用主模型配置（用于执行阶段权限下放）。
        """
        self.page = page
        self.site_url = site_url
        self.user_request = user_request
        self.output_dir = output_dir
        self.selected_skills_context = str(selected_skills_context or "")
        self.selected_skills = list(selected_skills or [])
        self.planner_intent = (
            planner_intent
            if isinstance(planner_intent, PlannerIntent)
            else PlannerIntent.from_payload(planner_intent)
        )
        self._knowledge_entries: list[dict] = []  # 规划发现过程中收集的知识条目
        self._journal_entries: list[dict] = []
        self._sibling_category_registry: dict[str, set[str]] = {}
        self._page_state = PlannerPageState(page)
        self._artifacts = PlannerArtifacts(
            site_url=site_url,
            user_request=user_request,
            output_dir=output_dir,
        )
        self.planner_status = "success"
        self.terminal_reason = ""

        if use_main_model:
            api_key = config.llm.api_key
            api_base = config.llm.api_base
            model = config.llm.model
        else:
            api_key = config.llm.planner_api_key or config.llm.api_key
            api_base = config.llm.planner_api_base or config.llm.api_base
            model = config.llm.planner_model or config.llm.model

        # 初始化 ChatOpenAI 实例
        self.llm = ChatOpenAI(
            api_key=api_key,
            base_url=api_base,
            model=model,
            temperature=config.llm.temperature,
            max_tokens=config.llm.max_tokens,
            model_kwargs={"response_format": {"type": "json_object"}},
            extra_body={"enable_thinking": config.llm.enable_thinking},
        )

    async def plan(self) -> TaskPlan:
        """只为入口页面生成首层子任务。"""
        logger.info("[Planner] 开始首层任务规划: %s", self.site_url)

        await self.page.goto(self.site_url, wait_until="domcontentloaded", timeout=30000)
        await self._wait_for_planner_page_ready()
        logger.info("[Planner] 页面已加载: %s", self.page.url)

        subtasks = await self._plan_entry_subtasks()
        plan = self._build_plan(subtasks)
        plan = self._save_plan(plan)
        self._write_knowledge_doc(plan)
        self._sediment_draft_skill(plan)

        logger.info("[Planner] 首层规划完成，发现 %d 个一级任务", len(plan.subtasks))
        return plan

    async def _plan_entry_subtasks(self) -> list[SubTask]:
        current_url = self.page.url
        current_context: dict[str, str] = {}
        current_nav_steps: list[dict] = []
        snapshot = await inject_and_scan(self.page)
        _, screenshot_base64 = await capture_screenshot_with_marks(self.page)
        await clear_overlay(self.page)

        analysis = await self._analyze_site_structure(
            screenshot_base64,
            snapshot,
            node_context=current_context,
            nav_steps=current_nav_steps,
        )
        if not analysis:
            logger.warning("[Planner] 入口页面分析失败")
            self.planner_status = "error"
            self.terminal_reason = "planner_error"
            return []

        page_type = str(analysis.get("page_type", "category")).strip().lower()
        node_name = str(analysis.get("name", "")).strip() or "入口页面"
        observations = str(analysis.get("observations", "")).strip()
        node_id = self._next_node_id()
        state_signature = self._build_page_state_signature(current_url, current_nav_steps)
        node_type = self._resolve_plan_node_type_for_state(page_type, current_nav_steps)

        entry_index = len(self._knowledge_entries)
        self._knowledge_entries.append({
            "node_id": node_id,
            "parent_node_id": None,
            "depth": 0,
            "url": current_url,
            "anchor_url": current_url,
            "page_state_signature": state_signature,
            "variant_label": None,
            "page_type": page_type,
            "name": node_name,
            "observations": observations,
            "children_count": 0,
            "is_leaf": False,
            "task_description": str(analysis.get("task_description", self.user_request) or self.user_request),
            "context": {},
            "nav_steps": [],
            "subtask_id": None,
            "executable": False,
            "node_type": node_type.value,
        })
        self._append_journal(
            node_id=node_id,
            phase="planning",
            action="analyze_page",
            reason=f"入口页面识别为 {page_type}",
            evidence=observations,
            metadata={"url": current_url, "depth": "0"},
        )

        if page_type == "list_page":
            collect_desc = str(analysis.get("task_description") or "").strip() or self._build_collect_task_description(current_context)
            collect_brief = self._build_collect_execution_brief(current_context, task_description=collect_desc)
            subtask = SubTask(
                id="leaf_001",
                name=node_name,
                list_url=current_url,
                anchor_url=current_url,
                page_state_signature=state_signature,
                task_description=collect_desc,
                nav_steps=[],
                depth=0,
                priority=0,
                context=current_context,
                plan_node_id=node_id,
                mode=SubTaskMode.COLLECT,
                execution_brief=collect_brief,
            )
            self._knowledge_entries[entry_index]["is_leaf"] = True
            self._knowledge_entries[entry_index]["executable"] = True
            self._knowledge_entries[entry_index]["subtask_id"] = subtask.id
            self._append_journal(
                node_id=node_id,
                phase="planning",
                action="register_leaf_subtask",
                reason="入口页面可直接采集，生成 collect 任务",
                evidence=collect_desc,
                metadata={"subtask_id": subtask.id, "mode": subtask.mode.value},
            )
            return [subtask]

        raw_children = list(analysis.get("subtasks") or [])
        if not raw_children:
            self.planner_status = "no_subtasks"
            self.terminal_reason = "planner_no_subtasks"
            self._record_planning_dead_end(
                entry_index=entry_index,
                node_id=node_id,
                reason="入口分类页未识别出首层子分类",
                evidence=observations or self.user_request,
                metadata={"url": current_url, "depth": "0"},
            )
            return []

        child_variants = await self._extract_subtask_variants(
            analysis,
            snapshot,
            current_nav_steps,
            parent_context=current_context,
        )
        if not child_variants:
            self.planner_status = "no_subtasks"
            self.terminal_reason = "planner_no_subtasks"
            self._record_planning_dead_end(
                entry_index=entry_index,
                node_id=node_id,
                reason="入口分类页未生成有效状态任务",
                evidence=self.user_request,
                metadata={"url": current_url, "depth": "0"},
            )
            return []

        subtasks = self._build_subtasks_from_variants(
            child_variants,
            analysis=analysis,
            depth=0,
            mode=SubTaskMode.EXPAND,
        )
        if not subtasks:
            self.planner_status = "no_subtasks"
            self.terminal_reason = "planner_no_subtasks"
            self._record_planning_dead_end(
                entry_index=entry_index,
                node_id=node_id,
                reason="入口分类页未生成首层子任务",
                evidence=self.user_request,
                metadata={"url": current_url, "depth": "0"},
            )
            return []

        self._knowledge_entries[entry_index]["children_count"] = len(subtasks)
        self._append_journal(
            node_id=node_id,
            phase="planning",
            action="expand_category",
            reason=f"生成 {len(subtasks)} 个一级 expand 任务",
            evidence="; ".join(subtask.name for subtask in subtasks),
            metadata={"children_count": str(len(subtasks))},
        )
        for subtask in subtasks:
            self._record_planned_subtask_node(
                subtask=subtask,
                parent_node_id=node_id,
                reason="入口页面拆分出的一级任务",
            )
        return subtasks

    def _record_planning_dead_end(
        self,
        *,
        entry_index: int,
        node_id: str,
        reason: str,
        evidence: str,
        metadata: dict[str, str] | None = None,
    ) -> None:
        self._knowledge_entries[entry_index]["children_count"] = 0
        self._knowledge_entries[entry_index]["is_leaf"] = False
        self._knowledge_entries[entry_index]["executable"] = False
        self._append_journal(
            node_id=node_id,
            phase="planning",
            action="planning_dead_end",
            reason=reason,
            evidence=evidence,
            metadata=dict(metadata or {}),
        )

    def _record_planned_subtask_node(
        self,
        *,
        subtask: SubTask,
        parent_node_id: str | None,
        reason: str,
    ) -> None:
        node_id = self._next_node_id()
        self._knowledge_entries.append({
            "node_id": node_id,
            "parent_node_id": parent_node_id,
            "depth": int(subtask.depth or 0),
            "url": subtask.list_url,
            "anchor_url": subtask.anchor_url or subtask.list_url,
            "page_state_signature": subtask.page_state_signature,
            "variant_label": subtask.variant_label,
            "page_type": "list_page" if subtask.mode == SubTaskMode.COLLECT else "category",
            "name": subtask.name,
            "observations": "",
            "children_count": 0,
            "is_leaf": subtask.mode == SubTaskMode.COLLECT,
            "task_description": subtask.task_description,
            "context": dict(subtask.context or {}),
            "nav_steps": list(subtask.nav_steps or []),
            "subtask_id": subtask.id,
            "executable": True,
            "node_type": (
                PlanNodeType.STATEFUL_LIST.value
                if subtask.mode == SubTaskMode.COLLECT and list(subtask.nav_steps or [])
                else (PlanNodeType.LEAF.value if subtask.mode == SubTaskMode.COLLECT else PlanNodeType.CATEGORY.value)
            ),
        })
        self._append_journal(
            node_id=node_id,
            phase="planning",
            action="create_subtask",
            reason=reason,
            evidence=subtask.task_description,
            metadata={
                "subtask_id": subtask.id,
                "mode": subtask.mode.value,
                "page_state_signature": str(subtask.page_state_signature or ""),
            },
        )

    def _append_observation_note(self, result: dict, note: str) -> dict:
        observations = str(result.get("observations") or "").strip()
        result["observations"] = f"{observations}\n{note}".strip() if observations else note
        return result

    def _get_grouping_semantics(self) -> dict[str, Any]:
        return self.planner_intent.model_dump(mode="python")

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

    def _build_page_state_signature(self, current_url: str, nav_steps: list[dict] | None) -> str:
        """构造 URL + nav_steps 的稳定状态签名。"""
        return self._page_state.build_page_state_signature(current_url, nav_steps)

    async def _restore_page_state(self, target_url: str, nav_steps: list[dict] | None) -> bool:
        """恢复到指定页面状态：先回到 anchor URL，再重放导航动作。"""
        return await self._page_state.restore_page_state(target_url, nav_steps)

    async def _enter_child_state(
        self,
        current_url: str,
        child_url: str,
        child_nav_steps: list[dict] | None,
        current_nav_steps: list[dict] | None,
    ) -> bool:
        """进入子节点状态，兼容普通跳转与同 URL 内态切换。"""
        return await self._page_state.enter_child_state(
            current_url,
            child_url,
            child_nav_steps,
            current_nav_steps,
        )

    async def _analyze_site_structure(
        self,
        screenshot_base64: str,
        snapshot: object,
        *,
        node_context: dict[str, str] | None = None,
        nav_steps: list[dict] | None = None,
    ) -> dict | None:
        """调用 LLM 视觉接口，分析带 SoM 标注的页面截图。

        Args:
            screenshot_base64: Base64 编码的页面截图（默认不含 SoM 标注框）。
            snapshot: SoM 扫描快照（用于构建候选元素列表）。

        Returns:
            dict | None: 解析后的 JSON 对象，包含 subtasks 列表；如果失败则返回 None。
        """
        # 渲染系统提示词和用户提示词
        system_prompt = render_template(
            PROMPT_TEMPLATE_PATH,
            section="analyze_site_system_prompt",
        )

        user_message = render_template(
            PROMPT_TEMPLATE_PATH,
            section="analyze_site_user_message",
            variables={
                "user_request": self.user_request,
                "current_url": self.page.url,
                "current_category_path": self._format_context_path(node_context),
                "recent_actions": self._format_recent_actions(nav_steps),
                "candidate_elements": self._build_planner_candidates(snapshot),
                "grouping_semantics": self._format_grouping_semantics(),
                "selected_skills_context": self.selected_skills_context or "当前未选择任何站点 skills。",
            },
        )

        # 构建多模态消息列表
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

        try:
            logger.info("[Planner] 调用 LLM 进行多模态视觉分析...")
            response = await ainvoke_with_stream(self.llm, messages)
            response_text = extract_response_text_from_llm_payload(response)
            response_summary = summarize_llm_payload(response)

            # 从 LLM 响应中解析 JSON 字典
            result = parse_json_dict_from_llm(response_text)
            append_llm_trace(
                component="planner_site_analysis",
                payload={
                    "model": getattr(self.llm, "model_name", None)
                    or getattr(self.llm, "model", None)
                    or config.llm.planner_model
                    or config.llm.model,
                    "input": {
                        "system_prompt": system_prompt,
                        "user_message": user_message,
                        "current_url": self.page.url,
                        "site_url": self.site_url,
                        "user_request": self.user_request,
                        "node_context": dict(node_context or {}),
                        "nav_steps": list(nav_steps or []),
                        "candidate_count": len(getattr(snapshot, "marks", []) or []),
                        "grouping_semantics": self._get_grouping_semantics(),
                        "selected_skills": list(self.selected_skills or []),
                    },
                    "output": {
                        "raw_response": response_text,
                        "parsed_payload": result,
                    },
                    "response_summary": response_summary,
                },
            )
            if result:
                result = self._post_process_analysis(result, snapshot, node_context=node_context)
                subtask_count = len(result.get("subtasks", []))
                logger.info("[Planner] LLM 识别到 %d 个候选分类", subtask_count)
                return result

            logger.warning("[Planner] LLM 响应内容不符合预期的 JSON 格式: %s", str(response_text)[:200])
        except Exception as e:
            append_llm_trace(
                component="planner_site_analysis",
                payload={
                    "model": getattr(self.llm, "model_name", None)
                    or getattr(self.llm, "model", None)
                    or config.llm.planner_model
                    or config.llm.model,
                    "input": {
                        "system_prompt": system_prompt,
                        "user_message": user_message,
                        "current_url": self.page.url,
                        "site_url": self.site_url,
                        "user_request": self.user_request,
                        "node_context": dict(node_context or {}),
                        "nav_steps": list(nav_steps or []),
                        "candidate_count": len(getattr(snapshot, "marks", []) or []),
                        "grouping_semantics": self._get_grouping_semantics(),
                        "selected_skills": list(self.selected_skills or []),
                    },
                    "output": {},
                    "response_summary": {},
                    "error": {
                        "type": type(e).__name__,
                        "message": str(e),
                    },
                },
            )
            logger.exception("[Planner] 调用 LLM 分析网站结构时发生异常")

        return None

    async def plan_runtime_subtasks(
        self,
        *,
        parent_subtask: SubTask,
        max_children: int | None = None,
    ) -> RuntimeSubtaskPlanResult:
        current_url = str(parent_subtask.anchor_url or parent_subtask.list_url or self.site_url).strip()
        current_nav_steps = list(parent_subtask.nav_steps or [])
        current_context = self._sanitize_context(parent_subtask.context)
        restored = await self._restore_page_state(current_url, current_nav_steps)
        if not restored:
            raise RuntimeError("runtime_subtask_restore_failed")

        snapshot = await inject_and_scan(self.page)
        _, screenshot_base64 = await capture_screenshot_with_marks(self.page)
        await clear_overlay(self.page)

        analysis = await self._analyze_site_structure(
            screenshot_base64,
            snapshot,
            node_context=current_context,
            nav_steps=current_nav_steps,
        )
        if not analysis:
            raise RuntimeError("runtime_subtask_analysis_failed")

        page_type = str(analysis.get("page_type", "category")).strip().lower()
        collect_desc = str(analysis.get("task_description") or "").strip() or self._build_collect_task_description(current_context)
        collect_brief = self._build_collect_execution_brief(
            current_context,
            task_description=collect_desc,
            parent_execution_brief=parent_subtask.execution_brief,
        )
        if page_type == "list_page":
            return RuntimeSubtaskPlanResult(
                page_type=page_type,
                analysis=analysis,
                collect_task_description=collect_desc,
                collect_execution_brief=collect_brief,
            )

        child_variants = await self._extract_subtask_variants(
            analysis,
            snapshot,
            parent_nav_steps=current_nav_steps,
            parent_context=current_context,
        )
        children = self._build_subtasks_from_variants(
            child_variants,
            analysis=analysis,
            depth=int(parent_subtask.depth or 0),
            mode=SubTaskMode.EXPAND,
            parent_id=parent_subtask.id,
            parent_execution_brief=parent_subtask.execution_brief,
        )
        if max_children is not None and max_children > 0:
            children = children[:max_children]
        if not children:
            return RuntimeSubtaskPlanResult(
                page_type="list_page",
                analysis=analysis,
                collect_task_description=collect_desc,
                collect_execution_brief=collect_brief,
            )

        return RuntimeSubtaskPlanResult(
            page_type=page_type,
            analysis=analysis,
            children=children,
            collect_task_description=collect_desc,
            collect_execution_brief=collect_brief,
        )

    def _build_nav_click_step(self, snapshot: object, mark_id: int) -> dict | None:
        """基于 snapshot 为 planner 构造可回放的点击动作。"""
        return self._page_state.build_nav_click_step(snapshot, mark_id)

    async def _get_dom_signature(self) -> str:
        """获取页面 DOM 内容签名，用于检测内容变化。"""
        return await self._page_state.get_dom_signature()

    async def _get_element_interaction_state(self, xpath: str) -> dict[str, str]:
        """获取候选分类元素的交互状态（active/selected 等）。"""
        return await self._page_state.get_element_interaction_state(xpath)

    def _did_interaction_state_activate(
        self,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
    ) -> bool:
        """判断点击后元素是否进入激活态。"""
        return self._page_state.did_interaction_state_activate(before, after)

    async def _restore_original_page(self, original_url: str) -> None:
        """回退到原始页面，等待 SPA 渲染完成。"""
        await self._page_state.restore_original_page(original_url)

    async def _wait_for_planner_page_ready(self) -> None:
        """等待入口页的 SPA 内容稳定，避免过早截图导致分类状态缺失。"""
        try:
            await self.page.wait_for_load_state("networkidle", timeout=_PLANNER_READY_TIMEOUT_MS)
        except Exception:
            pass
        await self.page.wait_for_timeout(_PLANNER_READY_FALLBACK_WAIT_MS)

    def _build_plan(self, subtasks: list[SubTask]) -> TaskPlan:
        """构造 TaskPlan 响应对象。"""
        return self._artifacts.build_plan(
            subtasks,
            nodes=self._build_plan_nodes(),
            journal=self._build_plan_journal(),
        )

    def _build_plan_id(self) -> str:
        return self._artifacts._build_plan_id()

    def _load_saved_plan(self) -> TaskPlan | None:
        return self._artifacts._load_saved_plan()

    def _create_empty_plan(self) -> TaskPlan:
        """当分析失败或 LLM 未产生结果时，返回一个没有任何子任务的空计划。"""
        return self._artifacts.create_empty_plan()

    def _save_plan(self, plan: TaskPlan) -> TaskPlan:
        """将生成的任务计划序列化为 JSON 文件，存储在指定的输出目录中。"""
        return self._artifacts.save_plan(plan)

    def _write_knowledge_doc(self, plan: TaskPlan) -> None:
        """将规划发现过程写成层次化的 Markdown 知识文档。"""
        self._artifacts.write_knowledge_doc(plan)

    def render_plan_knowledge(self, plan: TaskPlan) -> str:
        return self._artifacts.build_knowledge_doc(plan)

    def _sediment_draft_skill(self, plan: TaskPlan) -> None:
        """规划完成后立即生成 draft Skill，不等 Worker 执行。"""
        self._artifacts.sediment_draft_skill(plan)

    def _build_plan_nodes(self) -> list[PlanNode]:
        nodes: list[PlanNode] = []
        for raw in self._knowledge_entries:
            node_type = self._resolve_plan_node_type(raw)
            nodes.append(
                PlanNode(
                    node_id=str(raw.get("node_id") or ""),
                    parent_node_id=str(raw.get("parent_node_id") or "") or None,
                    name=str(raw.get("name") or ""),
                    node_type=node_type,
                    url=str(raw.get("url") or ""),
                    anchor_url=str(raw.get("anchor_url") or "") or None,
                    page_state_signature=str(raw.get("page_state_signature") or "") or None,
                    variant_label=str(raw.get("variant_label") or "") or None,
                    task_description=str(raw.get("task_description") or ""),
                    observations=str(raw.get("observations") or ""),
                    depth=int(raw.get("depth", 0) or 0),
                    nav_steps=list(raw.get("nav_steps") or []),
                    context=dict(raw.get("context") or {}),
                    subtask_id=str(raw.get("subtask_id") or "") or None,
                    is_leaf=bool(raw.get("is_leaf", False)),
                    executable=bool(raw.get("executable", False)),
                    children_count=int(raw.get("children_count", 0) or 0),
                )
            )
        return nodes

    def _resolve_plan_node_type(self, raw: dict[str, Any]) -> PlanNodeType:
        raw_type = str(raw.get("node_type") or raw.get("page_type") or "").strip()
        if raw.get("is_leaf") and raw_type not in {PlanNodeType.STATEFUL_LIST.value, PlanNodeType.LEAF.value}:
            return PlanNodeType.LEAF
        try:
            return PlanNodeType(raw_type)
        except ValueError:
            if raw.get("is_leaf"):
                return PlanNodeType.LEAF
            return PlanNodeType.CATEGORY

    def _build_plan_journal(self) -> list[PlanJournalEntry]:
        entries: list[PlanJournalEntry] = []
        for raw in self._journal_entries:
            entries.append(
                PlanJournalEntry(
                    entry_id=str(raw.get("entry_id") or ""),
                    node_id=str(raw.get("node_id") or "") or None,
                    phase=str(raw.get("phase") or ""),
                    action=str(raw.get("action") or ""),
                    reason=str(raw.get("reason") or ""),
                    evidence=str(raw.get("evidence") or ""),
                    metadata={str(k): str(v) for k, v in dict(raw.get("metadata") or {}).items()},
                    created_at=str(raw.get("created_at") or ""),
                )
            )
        return entries

    def _append_journal(
        self,
        *,
        node_id: str | None,
        phase: str,
        action: str,
        reason: str,
        evidence: str = "",
        metadata: dict[str, str] | None = None,
    ) -> None:
        self._journal_entries.append({
            "entry_id": self._next_journal_id(),
            "node_id": node_id,
            "phase": phase,
            "action": action,
            "reason": reason,
            "evidence": evidence,
            "metadata": dict(metadata or {}),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })

    def _next_node_id(self) -> str:
        return f"node_{len(self._knowledge_entries) + 1:03d}"

    def _next_journal_id(self) -> str:
        return f"journal_{len(self._journal_entries) + 1:04d}"
