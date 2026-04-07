"""Runtime expansion service for expand-mode subtasks."""

from __future__ import annotations

from dataclasses import dataclass

from ..common.browser import BrowserSession
from ..contracts import ExpandRequest
from ..crawler.planner import TaskPlanner
from ..domain.planning import SubTask, SubTaskMode


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
        browser_session_cls: type = BrowserSession,
        planner_cls: type = TaskPlanner,
    ) -> None:
        self._browser_session_cls = browser_session_cls
        self._planner_cls = planner_cls

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
            planner = self._planner_cls(
                page=session.page,
                site_url=str(subtask.anchor_url or subtask.list_url or ""),
                user_request=str(subtask.task_description or ""),
                output_dir=output_dir,
                use_main_model=use_main_model,
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
