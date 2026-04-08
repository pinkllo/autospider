"""Dispatch use case。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ..common.browser.intervention import BrowserInterventionRequired
from ..contracts import PipelineMode, SubtaskOutcomeType
from ..domain.planning import ExecutionBrief, SubTask, SubTaskMode, SubTaskStatus, TaskPlan
from ..domain.runtime import SubTaskRuntimeState
from ..pipeline.worker import SubTaskWorker
from ..services.plan_mutation_service import PlanMutationService


class DispatchResult(BaseModel):
    task_plan: TaskPlan
    plan_knowledge: str = ""
    dispatch_queue: list[dict[str, Any]] = Field(default_factory=list)
    subtask_results: list[SubTaskRuntimeState] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


class DispatchUseCase:
    """调度层唯一入口。"""

    def __init__(self, *, mutation_service: PlanMutationService | None = None) -> None:
        self._mutation_service = mutation_service or PlanMutationService()

    @staticmethod
    def restore_subtask(payload: dict[str, Any]) -> SubTask:
        return SubTask.model_validate(dict(payload or {}))

    @staticmethod
    def inherit_parent_nav_steps(payload: dict[str, Any], plan: TaskPlan) -> dict[str, Any]:
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
    def subtask_signature(payload: dict[str, Any]) -> tuple[str, str, str, str, str]:
        return (
            str(payload.get("page_state_signature") or "").strip(),
            str(payload.get("anchor_url") or "").strip(),
            str(payload.get("variant_label") or "").strip(),
            str(payload.get("task_description") or "").strip(),
            str(payload.get("parent_id") or "").strip(),
        )

    @staticmethod
    def _is_reliable(result: dict[str, Any] | None) -> bool:
        summary = dict((result or {}).get("summary") or {})
        outcome_type = str((result or {}).get("outcome_type") or "").strip().lower()
        if outcome_type in {SubtaskOutcomeType.NO_DATA.value, SubtaskOutcomeType.EXPANDED.value}:
            return False
        execution_state = str(summary.get("execution_state") or "").strip().lower()
        durability_state = str(summary.get("durability_state") or "").strip().lower()
        if execution_state and execution_state != "completed":
            return False
        return durability_state == "durable"

    @classmethod
    def resolve_status(cls, result: dict[str, Any]) -> SubTaskStatus:
        outcome_type = str(result.get("outcome_type") or "").strip().lower()
        if outcome_type == SubtaskOutcomeType.EXPANDED.value:
            return SubTaskStatus.EXPANDED
        if outcome_type == SubtaskOutcomeType.NO_DATA.value:
            return SubTaskStatus.NO_DATA
        if outcome_type == SubtaskOutcomeType.SYSTEM_FAILURE.value:
            return SubTaskStatus.SYSTEM_FAILURE
        if outcome_type == SubtaskOutcomeType.BUSINESS_FAILURE.value:
            return SubTaskStatus.BUSINESS_FAILURE
        execution_state = str(result.get("execution_state") or "").strip().lower()
        outcome_state = str(result.get("outcome_state") or "").strip().lower()
        durability_state = str(result.get("durability_state") or "").strip().lower()
        error = str(result.get("error") or "").strip()
        if execution_state == SubTaskStatus.EXPANDED.value:
            return SubTaskStatus.EXPANDED
        if outcome_state == "no_data":
            return SubTaskStatus.NO_DATA
        if error or outcome_state == "system_failure" or execution_state == "failed":
            return SubTaskStatus.SYSTEM_FAILURE
        if durability_state != "durable":
            return SubTaskStatus.SYSTEM_FAILURE
        if int(result.get("failed_count", 0) or 0) > 0:
            return SubTaskStatus.BUSINESS_FAILURE
        return SubTaskStatus.COMPLETED

    @classmethod
    def build_runtime_state(
        cls,
        subtask: SubTask,
        *,
        status: SubTaskStatus,
        error: str = "",
        result: dict[str, Any] | None = None,
        expand_request: dict[str, Any] | None = None,
    ) -> SubTaskRuntimeState:
        run_result = dict(result or {})
        outcome_type = str(run_result.get("outcome_type") or "").strip().lower()
        summary = {
            "total_urls": int(run_result.get("total_urls", 0) or 0),
            "success_count": int(run_result.get("success_count", 0) or 0),
            "failed_count": int(run_result.get("failed_count", 0) or 0),
            "success_rate": float(run_result.get("success_rate", 0.0) or 0.0),
            "required_field_success_rate": float(run_result.get("required_field_success_rate", 0.0) or 0.0),
            "validation_failure_count": int(run_result.get("validation_failure_count", 0) or 0),
            "execution_state": str(run_result.get("execution_state") or ""),
            "outcome_state": str(run_result.get("outcome_state") or ""),
            "terminal_reason": str(run_result.get("terminal_reason") or ""),
            "promotion_state": str(run_result.get("promotion_state") or ""),
            "execution_id": str(run_result.get("execution_id") or ""),
            "items_file": str(run_result.get("items_file") or ""),
            "durability_state": str(run_result.get("durability_state") or ""),
            "durably_persisted": bool(run_result.get("durably_persisted")),
            "reliable_for_aggregation": cls._is_reliable(
                {"summary": run_result, "outcome_type": outcome_type}
            ),
        }
        return SubTaskRuntimeState.model_validate(
            {
                "subtask_id": subtask.id,
                "name": subtask.name,
                "list_url": subtask.list_url,
                "anchor_url": str(subtask.anchor_url or ""),
                "page_state_signature": str(subtask.page_state_signature or ""),
                "variant_label": str(subtask.variant_label or ""),
                "task_description": subtask.task_description,
                "mode": str(subtask.mode.value),
                "execution_brief": subtask.execution_brief.model_dump(mode="python"),
                "parent_id": str(subtask.parent_id or ""),
                "depth": int(subtask.depth or 0),
                "context": dict(subtask.context or {}),
                "status": status.value,
                "outcome_type": outcome_type,
                "error": error,
                "retry_count": int(subtask.retry_count or 0),
                "result_file": str(run_result.get("items_file") or subtask.result_file or ""),
                "collected_count": int(run_result.get("total_urls", 0) or subtask.collected_count or 0),
                "summary": summary,
                "collection_config": dict(run_result.get("collection_config") or {}),
                "extraction_config": dict(run_result.get("extraction_config") or {}),
                "extraction_evidence": list(run_result.get("extraction_evidence") or []),
                "validation_failures": list(run_result.get("validation_failures") or []),
                "journal_entries": list(run_result.get("journal_entries") or []),
                "expand_request": dict(expand_request or {}),
            }
        )

    async def run_subtask(
        self,
        *,
        subtask_payload: dict[str, Any],
        params: dict[str, Any],
        plan: TaskPlan | None,
        plan_knowledge: str,
    ) -> tuple[SubTaskRuntimeState, dict[str, Any], list[dict[str, str]]]:
        subtask = self.restore_subtask(subtask_payload)
        if subtask.max_pages is None and params.get("max_pages") is not None:
            subtask.max_pages = int(params["max_pages"])
        if subtask.target_url_count is None and params.get("target_url_count") is not None:
            subtask.target_url_count = int(params["target_url_count"])
        worker = SubTaskWorker(
            subtask=subtask,
            fields=list(getattr(plan, "shared_fields", []) or []),
            output_dir=str(params.get("output_dir") or "output"),
            headless=params.get("headless"),
            thread_id=str(params.get("_thread_id") or ""),
            guard_intervention_mode="interrupt",
            consumer_concurrency=int(params["consumer_concurrency"]) if params.get("consumer_concurrency") is not None else None,
            field_explore_count=int(params["field_explore_count"]) if params.get("field_explore_count") is not None else None,
            field_validate_count=int(params["field_validate_count"]) if params.get("field_validate_count") is not None else None,
            selected_skills=list(params.get("selected_skills") or []),
            plan_knowledge=plan_knowledge,
            task_plan_snapshot=plan.model_dump(mode="python") if isinstance(plan, TaskPlan) else {},
            plan_journal=[entry.model_dump(mode="python") for entry in list(getattr(plan, "journal", []) or [])]
            if isinstance(plan, TaskPlan)
            else [],
            pipeline_mode=PipelineMode(str(params.get("pipeline_mode") or "").strip().lower())
            if str(params.get("pipeline_mode") or "").strip()
            else None,
        )
        while True:
            try:
                result = await worker.execute()
                break
            except BrowserInterventionRequired:
                raise

        effective_subtask = self.restore_subtask(result.get("effective_subtask") or subtask.model_dump(mode="python"))
        expand_request = dict(result.get("expand_request") or {})
        status = self.resolve_status(result)
        error = str(result.get("error") or "").strip()
        if not error and status == SubTaskStatus.SYSTEM_FAILURE:
            error = "subtask_result_not_durable"
        runtime_state = self.build_runtime_state(
            effective_subtask,
            status=status,
            error=error[:500],
            result=result,
            expand_request=expand_request,
        )
        artifacts = []
        if str(result.get("items_file") or "").strip():
            artifacts.append({"label": "subtask_items", "path": str(result["items_file"])})
        return runtime_state, expand_request, artifacts

    def apply_result_to_plan(self, plan: TaskPlan, runtime_state: SubTaskRuntimeState | dict[str, Any]) -> None:
        if isinstance(runtime_state, dict):
            runtime_state = SubTaskRuntimeState.model_validate(runtime_state)
        for subtask in plan.subtasks:
            if subtask.id != runtime_state.subtask_id:
                continue
            subtask.status = SubTaskStatus(runtime_state.status)
            subtask.error = runtime_state.error or None
            subtask.result_file = runtime_state.result_file or None
            subtask.collected_count = runtime_state.collected_count
            if runtime_state.task_description:
                subtask.task_description = runtime_state.task_description
            if runtime_state.mode:
                subtask.mode = SubTaskMode(runtime_state.mode)
            if runtime_state.execution_brief:
                subtask.execution_brief = ExecutionBrief.model_validate(runtime_state.execution_brief)
            return

    def build_summary(self, plan: TaskPlan, runtime_states: list[SubTaskRuntimeState | dict[str, Any]]) -> dict[str, Any]:
        for runtime_state in runtime_states:
            self.apply_result_to_plan(plan, runtime_state)
        total = len(plan.subtasks)
        completed = sum(1 for subtask in plan.subtasks if subtask.status == SubTaskStatus.COMPLETED)
        no_data = sum(1 for subtask in plan.subtasks if subtask.status == SubTaskStatus.NO_DATA)
        expanded = sum(1 for subtask in plan.subtasks if subtask.status == SubTaskStatus.EXPANDED)
        business_failure = sum(1 for subtask in plan.subtasks if subtask.status == SubTaskStatus.BUSINESS_FAILURE)
        system_failure = sum(1 for subtask in plan.subtasks if subtask.status == SubTaskStatus.SYSTEM_FAILURE)
        skipped = sum(1 for subtask in plan.subtasks if subtask.status == SubTaskStatus.SKIPPED)
        total_collected = sum(int(subtask.collected_count or 0) for subtask in plan.subtasks if subtask.status == SubTaskStatus.COMPLETED)
        plan.total_subtasks = total
        if not plan.updated_at:
            plan.updated_at = plan.created_at
        return {
            "total": total,
            "completed": completed,
            "no_data": no_data,
            "expanded": expanded,
            "business_failure": business_failure,
            "system_failure": system_failure,
            "failed": business_failure + system_failure,
            "skipped": skipped,
            "total_collected": total_collected,
        }

    def merge_round(
        self,
        *,
        plan: TaskPlan,
        expand_requests: list[dict[str, Any]],
        pending_queue: list[dict[str, Any]],
        output_dir: str,
        subtask_results: list[dict[str, Any]],
    ) -> DispatchResult:
        runtime_states = [SubTaskRuntimeState.model_validate(item) for item in subtask_results]
        mutation_result = self._mutation_service.merge_expand_requests(
            plan=plan,
            expand_requests=expand_requests,
            pending_queue=pending_queue,
            output_dir=output_dir,
        )
        summary = self.build_summary(mutation_result.task_plan, runtime_states)
        return DispatchResult(
            task_plan=mutation_result.task_plan,
            plan_knowledge=mutation_result.plan_knowledge,
            dispatch_queue=list(mutation_result.dispatch_queue),
            subtask_results=runtime_states,
            summary=summary,
        )
