from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from autospider.platform.browser.runtime import BrowserRuntimeSession
from autospider.contexts.planning.application.dto import ReplanInput, TaskPlanDTO
from autospider.contexts.planning.application.use_cases.replan import Replan
from autospider.contexts.planning.domain.model import (
    PlanJournalEntry,
    SubTask,
    SubTaskMode,
    TaskPlan,
)
from autospider.contexts.planning.infrastructure.repositories.artifact_store import (
    ArtifactPlanRepository,
)
from autospider.composition.pipeline.types import ExpandRequest
from autospider.platform.shared_kernel.result import ResultEnvelope


class SubTaskFailedHandler:
    def __init__(self, replan_use_case: Replan) -> None:
        self._replan_use_case = replan_use_case

    def handle(
        self,
        *,
        plan: TaskPlan,
        reason: str,
        failed_subtask_id: str | None = None,
    ) -> ResultEnvelope[TaskPlanDTO]:
        return self._replan_use_case.run(
            ReplanInput(
                plan=plan,
                reason=reason,
                failed_subtask_id=failed_subtask_id,
            )
        )


@dataclass(frozen=True, slots=True)
class RuntimeExpansionResult:
    execution_state: str
    effective_subtask: SubTask
    journal_entries: tuple[dict[str, str], ...] = ()
    expand_request: ExpandRequest | None = None


class RuntimeExpansionService:
    """Runs runtime category analysis without mutating the task plan."""

    def __init__(
        self,
        *,
        browser_session_cls: type = BrowserRuntimeSession,
        planner_cls: type | None = None,
    ) -> None:
        self._browser_session_cls = browser_session_cls
        self._planner_cls = planner_cls

    def _resolve_planner_cls(self) -> type:
        if self._planner_cls is not None:
            return self._planner_cls
        # Deferred import avoids pulling TaskPlanner's heavy dependencies at module import time.
        from autospider.contexts.planning.infrastructure.adapters.task_planner import (
            TaskPlanner,
        )

        return TaskPlanner

    async def expand(
        self,
        *,
        subtask: SubTask,
        output_dir: str,
        headless: bool | None,
        thread_id: str,
        guard_intervention_mode: str,
        global_browser_budget: int,
        max_children: int,
        use_main_model: bool,
        decision_context: dict[str, Any] | None = None,
        world_snapshot: dict[str, Any] | None = None,
    ) -> RuntimeExpansionResult:
        session = self._browser_session_cls(
            headless=headless,
            guard_intervention_mode=guard_intervention_mode,
            guard_thread_id=thread_id,
            budget_key=thread_id or subtask.id,
            global_browser_budget=global_browser_budget,
        )
        await session.start()
        try:
            planner_cls = self._resolve_planner_cls()
            planner = planner_cls(
                page=session.page,
                site_url=str(subtask.anchor_url or subtask.list_url or ""),
                user_request=str(subtask.task_description or ""),
                output_dir=output_dir,
                use_main_model=use_main_model,
                decision_context=decision_context,
                world_snapshot=world_snapshot,
            )
            result = await planner.plan_runtime_subtasks(
                parent_subtask=subtask,
                max_children=max_children,
            )
        finally:
            await session.stop()

        if result.children:
            evidence = "; ".join(child.name for child in result.children)
            spawned = tuple(child.model_dump(mode="python") for child in result.children)
            journal_entries = (
                {
                    "entry_id": "",
                    "node_id": str(subtask.plan_node_id or ""),
                    "phase": "pipeline",
                    "action": "runtime_expand",
                    "reason": f"识别到 {len(result.children)} 个下级相关分类，当前任务转为 expanded",
                    "evidence": evidence,
                    "metadata": {"child_count": str(len(result.children))},
                    "created_at": "",
                },
                {
                    "entry_id": "",
                    "node_id": str(subtask.plan_node_id or ""),
                    "phase": "pipeline",
                    "action": "runtime_spawn_children",
                    "reason": "生成运行时子任务",
                    "evidence": "; ".join(child.task_description for child in result.children),
                    "metadata": {"spawned_ids": ",".join(child.id for child in result.children)},
                    "created_at": "",
                },
            )
            return RuntimeExpansionResult(
                execution_state="expanded",
                effective_subtask=subtask,
                journal_entries=journal_entries,
                expand_request=ExpandRequest(
                    parent_subtask_id=subtask.id,
                    spawned_subtasks=spawned,
                    journal_entries=journal_entries,
                    reason="runtime_expand",
                ),
            )

        collect_subtask = subtask.model_copy(
            update={
                "mode": SubTaskMode.COLLECT,
                "task_description": result.collect_task_description,
                "execution_brief": result.collect_execution_brief,
            }
        )
        journal_entries = (
            {
                "entry_id": "",
                "node_id": str(subtask.plan_node_id or ""),
                "phase": "pipeline",
                "action": "runtime_leaf_confirmed",
                "reason": "当前任务未识别到更深相关分类，确认为叶子采集任务",
                "evidence": str(result.analysis.get("observations") or ""),
                "metadata": {},
                "created_at": "",
            },
            {
                "entry_id": "",
                "node_id": str(subtask.plan_node_id or ""),
                "phase": "pipeline",
                "action": "runtime_expand_to_collect",
                "reason": "expand 任务就地转为 collect 执行",
                "evidence": result.collect_task_description,
                "metadata": {"mode": SubTaskMode.COLLECT.value},
                "created_at": "",
            },
        )
        return RuntimeExpansionResult(
            execution_state="collect",
            effective_subtask=collect_subtask,
            journal_entries=journal_entries,
        )


@dataclass(frozen=True, slots=True)
class PlanMutationResult:
    task_plan: TaskPlan
    dispatch_queue: tuple[dict[str, Any], ...]
    plan_knowledge: str


class PlanMutationService:
    """Merge runtime expand requests into an existing plan."""

    def __init__(
        self,
        *,
        artifact_factory: Callable[..., ArtifactPlanRepository] = ArtifactPlanRepository,
    ) -> None:
        self._artifact_factory = artifact_factory

    def merge_expand_requests(
        self,
        *,
        plan: TaskPlan,
        expand_requests: list[dict[str, Any]],
        pending_queue: list[dict[str, Any]],
        output_dir: str,
    ) -> PlanMutationResult:
        queue = list(pending_queue)
        known = {self._signature(subtask.model_dump(mode="python")) for subtask in plan.subtasks}
        self._merge_journal_entries(plan, expand_requests)
        for raw_request in expand_requests:
            for raw_subtask in list(raw_request.get("spawned_subtasks") or []):
                candidate = self._inherit_parent_nav_steps(raw_subtask, plan)
                signature = self._signature(candidate)
                if signature in known:
                    continue
                known.add(signature)
                plan.subtasks.append(SubTask.model_validate(candidate))
                queue.append(candidate)

        artifacts = self._artifact_factory(
            site_url=str(plan.site_url or ""),
            user_request=str(plan.original_request or ""),
            output_dir=output_dir,
        )
        plan.updated_at = datetime.now().isoformat(timespec="seconds")
        persisted_plan = artifacts.save_plan(plan)
        return PlanMutationResult(
            task_plan=persisted_plan,
            dispatch_queue=tuple(queue),
            plan_knowledge=artifacts.build_knowledge_doc(persisted_plan),
        )

    @staticmethod
    def _signature(payload: dict[str, Any]) -> tuple[str, str, str, str, str]:
        return (
            str(payload.get("page_state_signature") or "").strip(),
            str(payload.get("anchor_url") or "").strip(),
            str(payload.get("variant_label") or "").strip(),
            str(payload.get("task_description") or "").strip(),
            str(payload.get("parent_id") or "").strip(),
        )

    @staticmethod
    def _inherit_parent_nav_steps(payload: dict[str, Any], plan: TaskPlan) -> dict[str, Any]:
        hydrated = dict(payload or {})
        if hydrated.get("nav_steps"):
            return hydrated
        parent_id = str(hydrated.get("parent_id") or "").strip()
        if not parent_id:
            return hydrated
        for subtask in plan.subtasks:
            if subtask.id == parent_id:
                hydrated["nav_steps"] = list(subtask.nav_steps or [])
                return hydrated
        return hydrated

    @staticmethod
    def _merge_journal_entries(plan: TaskPlan, expand_requests: list[dict[str, Any]]) -> None:
        existing = {
            (
                str(entry.entry_id or ""),
                str(entry.phase or ""),
                str(entry.action or ""),
                str(entry.created_at or ""),
            )
            for entry in list(plan.journal or [])
        }
        for raw_request in expand_requests:
            for raw_entry in list(raw_request.get("journal_entries") or []):
                entry = dict(raw_entry or {})
                entry.setdefault("entry_id", f"runtime_{datetime.now().strftime('%H%M%S%f')}")
                entry.setdefault("created_at", datetime.now().isoformat(timespec="seconds"))
                key = (
                    str(entry.get("entry_id") or ""),
                    str(entry.get("phase") or ""),
                    str(entry.get("action") or ""),
                    str(entry.get("created_at") or ""),
                )
                if key in existing:
                    continue
                existing.add(key)
                plan.journal.append(PlanJournalEntry.model_validate(entry))
