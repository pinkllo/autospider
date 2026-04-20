from __future__ import annotations

from typing import Any

from autospider.platform.browser.som import (
    capture_screenshot_with_marks,
    clear_overlay,
    inject_and_scan,
)
from autospider.contexts.planning.domain import SubTask, SubTaskMode
from autospider.contexts.planning.infrastructure.adapters.analysis_support import (
    RuntimeSubtaskPlanResult,
)

_PLANNER_READY_TIMEOUT_MS = 5000
_PLANNER_READY_FALLBACK_WAIT_MS = 1500


class PlannerPageRuntimeMixin:
    def _build_page_state_signature(self, current_url: str, nav_steps: list[dict] | None) -> str:
        return self._page_state.build_page_state_signature(current_url, nav_steps)

    async def _restore_page_state(self, target_url: str, nav_steps: list[dict] | None) -> bool:
        return await self._page_state.restore_page_state(target_url, nav_steps)

    async def _enter_child_state(
        self,
        current_url: str,
        child_url: str,
        child_nav_steps: list[dict] | None,
        current_nav_steps: list[dict] | None,
    ) -> bool:
        return await self._page_state.enter_child_state(
            current_url,
            child_url,
            child_nav_steps,
            current_nav_steps,
        )

    async def plan_runtime_subtasks(
        self,
        *,
        parent_subtask: SubTask,
        max_children: int | None = None,
    ) -> RuntimeSubtaskPlanResult:
        current_url = str(
            parent_subtask.anchor_url or parent_subtask.list_url or self.site_url
        ).strip()
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

        collect_desc, collect_brief = self._build_runtime_collect_brief(
            analysis, current_context, parent_subtask
        )
        if str(analysis.get("page_type", "category")).strip().lower() == "list_page":
            return self._build_collect_runtime_result(analysis, collect_desc, collect_brief)

        return await self._build_runtime_expand_result(
            analysis=analysis,
            snapshot=snapshot,
            current_context=current_context,
            current_nav_steps=current_nav_steps,
            parent_subtask=parent_subtask,
            collect_desc=collect_desc,
            collect_brief=collect_brief,
            max_children=max_children,
        )

    def _build_runtime_collect_brief(
        self,
        analysis: dict[str, Any],
        current_context: dict[str, str],
        parent_subtask: SubTask,
    ) -> tuple[str, Any]:
        collect_desc = str(analysis.get("task_description") or "").strip()
        if not collect_desc:
            collect_desc = self._build_collect_task_description(current_context)
        collect_brief = self._build_collect_execution_brief(
            current_context,
            task_description=collect_desc,
            parent_execution_brief=parent_subtask.execution_brief,
        )
        return collect_desc, collect_brief

    def _build_collect_runtime_result(
        self,
        analysis: dict[str, Any],
        collect_desc: str,
        collect_brief: Any,
    ) -> RuntimeSubtaskPlanResult:
        return RuntimeSubtaskPlanResult(
            page_type="list_page",
            analysis=analysis,
            collect_task_description=collect_desc,
            collect_execution_brief=collect_brief,
        )

    async def _build_runtime_expand_result(
        self,
        *,
        analysis: dict[str, Any],
        snapshot: object,
        current_context: dict[str, str],
        current_nav_steps: list[dict],
        parent_subtask: SubTask,
        collect_desc: str,
        collect_brief: Any,
        max_children: int | None,
    ) -> RuntimeSubtaskPlanResult:
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
            return self._build_collect_runtime_result(analysis, collect_desc, collect_brief)
        return RuntimeSubtaskPlanResult(
            page_type=str(analysis.get("page_type", "category")).strip().lower(),
            analysis=analysis,
            children=children,
            collect_task_description=collect_desc,
            collect_execution_brief=collect_brief,
        )

    def _build_nav_click_step(self, snapshot: object, mark_id: int) -> dict | None:
        return self._page_state.build_nav_click_step(snapshot, mark_id)

    async def _get_dom_signature(self) -> str:
        return await self._page_state.get_dom_signature()

    async def _get_element_interaction_state(self, xpath: str) -> dict[str, str]:
        return await self._page_state.get_element_interaction_state(xpath)

    def _did_interaction_state_activate(
        self,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
    ) -> bool:
        return self._page_state.did_interaction_state_activate(before, after)

    async def _restore_original_page(self, original_url: str) -> None:
        await self._page_state.restore_original_page(original_url)

    async def _wait_for_planner_page_ready(self) -> None:
        try:
            await self.page.wait_for_load_state("networkidle", timeout=_PLANNER_READY_TIMEOUT_MS)
        except Exception:
            pass
        await self.page.wait_for_timeout(_PLANNER_READY_FALLBACK_WAIT_MS)
