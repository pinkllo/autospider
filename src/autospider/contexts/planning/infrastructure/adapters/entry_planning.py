from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from autospider.platform.browser.som import (
    capture_screenshot_with_marks,
    clear_overlay,
    inject_and_scan,
)
from autospider.platform.observability.logger import get_logger
from autospider.contexts.planning.domain import SubTask, SubTaskMode, TaskPlan

if TYPE_CHECKING:
    from playwright.async_api import Page

    from autospider.contexts.planning.domain import ExecutionBrief, PlanNodeType
    from autospider.contexts.planning.infrastructure.adapters.plan_records import (
        PlannerPlanRecordBook,
    )

logger = get_logger(__name__)


class PlannerEntryPageStateRuntime(Protocol):
    async def wait_for_planner_page_ready(self) -> None: ...

    def build_page_state_signature(
        self,
        current_url: str,
        nav_steps: list[dict] | None,
    ) -> str: ...


class PlannerEntryPlanningRuntime(Protocol):
    page: "Page"
    site_url: str
    user_request: str
    planner_status: str
    terminal_reason: str
    _plan_records: "PlannerPlanRecordBook"
    _page_state_runtime: PlannerEntryPageStateRuntime

    async def _analyze_site_structure(
        self,
        screenshot_base64: str,
        snapshot: object,
        *,
        node_context: dict[str, str] | None = None,
        nav_steps: list[dict] | None = None,
    ) -> dict | None: ...

    def _resolve_plan_node_type_for_state(
        self,
        page_type: str,
        nav_steps: list[dict] | None,
    ) -> "PlanNodeType": ...

    def _build_collect_task_description(self, context: dict[str, str] | None) -> str: ...

    def _build_collect_execution_brief(
        self,
        context: dict[str, str] | None,
        *,
        task_description: str,
    ) -> "ExecutionBrief": ...

    async def _extract_subtask_variants(
        self,
        analysis: dict,
        snapshot: object,
        parent_nav_steps: list[dict] | None = None,
        parent_context: dict[str, str] | None = None,
    ) -> list: ...

    def _build_subtasks_from_variants(
        self,
        variants: list,
        *,
        analysis: dict,
        depth: int,
        mode: SubTaskMode = SubTaskMode.COLLECT,
    ) -> list[SubTask]: ...


class PlannerEntryPlanner:
    def __init__(self, planner: PlannerEntryPlanningRuntime) -> None:
        self._planner = planner

    async def plan(self) -> TaskPlan:
        page = self._planner.page
        logger.info("[Planner] 开始首层任务规划: %s", self._planner.site_url)
        await page.goto(self._planner.site_url, wait_until="domcontentloaded", timeout=30000)
        await self._planner._page_state_runtime.wait_for_planner_page_ready()
        logger.info("[Planner] 页面已加载: %s", page.url)

        subtasks = await self._plan_entry_subtasks()
        plan = self._planner._plan_records.build_plan(subtasks)
        plan = self._planner._plan_records.save_plan(plan)
        self._planner._plan_records.write_knowledge_doc(plan)
        self._planner._plan_records.sediment_draft_skill(plan)

        logger.info("[Planner] 首层规划完成，发现 %d 个一级任务", len(plan.subtasks))
        return plan

    async def _plan_entry_subtasks(self) -> list[SubTask]:
        page = self._planner.page
        current_url = page.url
        current_context: dict[str, str] = {}
        current_nav_steps: list[dict] = []
        snapshot = await inject_and_scan(page)
        _, screenshot_base64 = await capture_screenshot_with_marks(page)
        await clear_overlay(page)

        analysis = await self._planner._analyze_site_structure(
            screenshot_base64,
            snapshot,
            node_context=current_context,
            nav_steps=current_nav_steps,
        )
        if not analysis:
            return self._handle_entry_analysis_failure()

        entry_index, node_id, page_type, observations = self._register_entry_analysis(
            analysis=analysis,
            current_url=current_url,
            current_nav_steps=current_nav_steps,
        )
        if page_type == "list_page":
            return [
                self._build_entry_collect_subtask(
                    analysis,
                    entry_index,
                    node_id,
                    current_context,
                    current_url,
                )
            ]
        return await self._build_entry_expand_subtasks(
            analysis=analysis,
            snapshot=snapshot,
            entry_index=entry_index,
            node_id=node_id,
            current_context=current_context,
            current_nav_steps=current_nav_steps,
            current_url=current_url,
            observations=observations,
        )

    def _handle_entry_analysis_failure(self) -> list[SubTask]:
        logger.warning("[Planner] 入口页面分析失败")
        self._planner.planner_status = "error"
        self._planner.terminal_reason = "planner_error"
        return []

    def _register_entry_analysis(
        self,
        *,
        analysis: dict[str, Any],
        current_url: str,
        current_nav_steps: list[dict],
    ) -> tuple[int, str, str, str]:
        page_type = str(analysis.get("page_type", "category")).strip().lower()
        node_name = str(analysis.get("name", "")).strip() or "入口页面"
        observations = str(analysis.get("observations", "")).strip()
        state_signature = self._planner._page_state_runtime.build_page_state_signature(
            current_url,
            current_nav_steps,
        )
        node_type = self._planner._resolve_plan_node_type_for_state(page_type, current_nav_steps)
        entry_index, node_id = self._planner._plan_records.register_entry_page(
            current_url=current_url,
            page_type=page_type,
            node_name=node_name,
            observations=observations,
            task_description=str(
                analysis.get("task_description", self._planner.user_request)
                or self._planner.user_request
            ),
            page_state_signature=state_signature,
            node_type=node_type,
        )
        self._planner._plan_records.append_journal(
            node_id=node_id,
            phase="planning",
            action="analyze_page",
            reason=f"入口页面识别为 {page_type}",
            evidence=observations,
            metadata={"url": current_url, "depth": "0"},
        )
        return entry_index, node_id, page_type, observations

    def _build_entry_collect_subtask(
        self,
        analysis: dict[str, Any],
        entry_index: int,
        node_id: str,
        current_context: dict[str, str],
        current_url: str,
    ) -> SubTask:
        collect_desc = str(analysis.get("task_description") or "").strip()
        if not collect_desc:
            collect_desc = self._planner._build_collect_task_description(current_context)
        collect_brief = self._planner._build_collect_execution_brief(
            current_context,
            task_description=collect_desc,
        )
        subtask = SubTask(
            id="leaf_001",
            name=str(analysis.get("name", "")).strip() or "入口页面",
            list_url=current_url,
            anchor_url=current_url,
            page_state_signature=self._planner._page_state_runtime.build_page_state_signature(
                current_url,
                [],
            ),
            task_description=collect_desc,
            nav_steps=[],
            depth=0,
            priority=0,
            context=current_context,
            plan_node_id=node_id,
            mode=SubTaskMode.COLLECT,
            execution_brief=collect_brief,
        )
        self._planner._plan_records.mark_entry_collectable(
            entry_index=entry_index,
            subtask_id=subtask.id,
        )
        self._planner._plan_records.append_journal(
            node_id=node_id,
            phase="planning",
            action="register_leaf_subtask",
            reason="入口页面可直接采集，生成 collect 任务",
            evidence=collect_desc,
            metadata={"subtask_id": subtask.id, "mode": subtask.mode.value},
        )
        return subtask

    async def _build_entry_expand_subtasks(
        self,
        *,
        analysis: dict[str, Any],
        snapshot: object,
        entry_index: int,
        node_id: str,
        current_context: dict[str, str],
        current_nav_steps: list[dict],
        current_url: str,
        observations: str,
    ) -> list[SubTask]:
        raw_children = list(analysis.get("subtasks") or [])
        if not raw_children:
            return self._mark_entry_without_subtasks(
                entry_index=entry_index,
                node_id=node_id,
                reason="入口分类页未识别出首层子分类",
                evidence=observations or self._planner.user_request,
                current_url=current_url,
            )

        child_variants = await self._planner._extract_subtask_variants(
            analysis,
            snapshot,
            current_nav_steps,
            parent_context=current_context,
        )
        if not child_variants:
            return self._mark_entry_without_subtasks(
                entry_index=entry_index,
                node_id=node_id,
                reason="入口分类页未生成有效状态任务",
                evidence=self._planner.user_request,
                current_url=current_url,
            )

        subtasks = self._planner._build_subtasks_from_variants(
            child_variants,
            analysis=analysis,
            depth=0,
            mode=SubTaskMode.EXPAND,
        )
        if not subtasks:
            return self._mark_entry_without_subtasks(
                entry_index=entry_index,
                node_id=node_id,
                reason="入口分类页未生成首层子任务",
                evidence=self._planner.user_request,
                current_url=current_url,
            )

        self._planner._plan_records.mark_entry_children(
            entry_index=entry_index,
            children_count=len(subtasks),
        )
        self._planner._plan_records.append_journal(
            node_id=node_id,
            phase="planning",
            action="expand_category",
            reason=f"生成 {len(subtasks)} 个一级 expand 任务",
            evidence="; ".join(subtask.name for subtask in subtasks),
            metadata={"children_count": str(len(subtasks))},
        )
        for subtask in subtasks:
            self._planner._plan_records.record_planned_subtask_node(
                subtask=subtask,
                parent_node_id=node_id,
                reason="入口页面拆分出的一级任务",
            )
        return subtasks

    def _mark_entry_without_subtasks(
        self,
        *,
        entry_index: int,
        node_id: str,
        reason: str,
        evidence: str,
        current_url: str,
    ) -> list[SubTask]:
        self._planner.planner_status = "no_subtasks"
        self._planner.terminal_reason = "planner_no_subtasks"
        self._planner._plan_records.record_planning_dead_end(
            entry_index=entry_index,
            node_id=node_id,
            reason=reason,
            evidence=evidence,
            metadata={"url": current_url, "depth": "0"},
        )
        return []
