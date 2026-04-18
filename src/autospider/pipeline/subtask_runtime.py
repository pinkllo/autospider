"""Canonical runtime helpers for subtask execution and dispatch."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..domain.planning import ExecutionBrief, SubTask, SubTaskMode, SubTaskStatus, TaskPlan
from ..domain.runtime import SubTaskRuntimeState
from .types import PipelineRunResult, PipelineRunSummary, SubtaskOutcomeType


def _read_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def restore_execution_brief(payload: dict[str, Any] | ExecutionBrief | None) -> ExecutionBrief:
    if isinstance(payload, ExecutionBrief):
        return payload
    return ExecutionBrief.model_validate(_read_mapping(payload))


def restore_subtask(payload: dict[str, Any] | SubTask) -> SubTask:
    if isinstance(payload, SubTask):
        return payload
    return SubTask.model_validate(_read_mapping(payload))


def subtask_to_payload(subtask: SubTask) -> dict[str, Any]:
    return subtask.model_dump(mode="python")


def _coerce_pipeline_result(result: PipelineRunResult | dict[str, Any] | None) -> PipelineRunResult:
    if isinstance(result, PipelineRunResult):
        return result
    return PipelineRunResult.from_raw(_read_mapping(result))


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


def subtask_signature(payload: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(payload.get("page_state_signature") or "").strip(),
        str(payload.get("anchor_url") or "").strip(),
        str(payload.get("variant_label") or "").strip(),
        str(payload.get("task_description") or "").strip(),
        str(payload.get("parent_id") or "").strip(),
    )


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


def _build_runtime_summary(run_result: PipelineRunResult) -> dict[str, Any]:
    summary: PipelineRunSummary = run_result.summary
    outcome_type = str(run_result.data.get("outcome_type") or "").strip().lower()
    return {
        "total_urls": summary.total_urls,
        "success_count": summary.success_count,
        "failed_count": summary.failed_count,
        "success_rate": summary.success_rate,
        "required_field_success_rate": summary.required_field_success_rate,
        "validation_failure_count": summary.validation_failure_count,
        "execution_state": summary.execution_state,
        "outcome_state": summary.outcome_state,
        "terminal_reason": summary.terminal_reason,
        "promotion_state": summary.promotion_state.value,
        "execution_id": summary.execution_id,
        "items_file": summary.items_file,
        "durability_state": summary.durability_state.value,
        "durably_persisted": summary.durably_persisted,
        "reliable_for_aggregation": _is_reliable({"summary": run_result.to_payload(), "outcome_type": outcome_type}),
        "failure_category": summary.failure_category,
        "failure_detail": summary.failure_detail,
    }


def resolve_subtask_status(result: dict[str, Any]) -> SubTaskStatus:
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
    success_count = int(result.get("success_count", 0) or 0)
    if execution_state == SubTaskStatus.EXPANDED.value:
        return SubTaskStatus.EXPANDED
    if outcome_state == "no_data":
        return SubTaskStatus.NO_DATA
    if error or outcome_state == "system_failure" or execution_state == "failed":
        return SubTaskStatus.SYSTEM_FAILURE
    if durability_state != "durable":
        return SubTaskStatus.SYSTEM_FAILURE
    if success_count <= 0:
        return SubTaskStatus.BUSINESS_FAILURE
    return SubTaskStatus.COMPLETED


def build_runtime_state(
    subtask: SubTask,
    *,
    status: SubTaskStatus,
    error: str = "",
    result: PipelineRunResult | dict[str, Any] | None = None,
    expand_request: dict[str, Any] | None = None,
) -> SubTaskRuntimeState:
    pipeline_result = _coerce_pipeline_result(result)
    payload = pipeline_result.to_payload()
    outcome_type = str(payload.get("outcome_type") or "").strip().lower()
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
            "execution_brief": restore_execution_brief(subtask.execution_brief).model_dump(mode="python"),
            "parent_id": str(subtask.parent_id or ""),
            "depth": int(subtask.depth or 0),
            "context": dict(subtask.context or {}),
            "status": status.value,
            "outcome_type": outcome_type,
            "error": error,
            "retry_count": int(subtask.retry_count or 0),
            "result_file": str(payload.get("items_file") or subtask.result_file or ""),
            "collected_count": int(payload.get("total_urls", 0) or subtask.collected_count or 0),
            "summary": _build_runtime_summary(pipeline_result),
            "collection_config": dict(pipeline_result.collection_config),
            "extraction_config": dict(pipeline_result.extraction_config),
            "extraction_evidence": list(pipeline_result.extraction_evidence),
            "validation_failures": list(pipeline_result.validation_failures),
            "journal_entries": list(payload.get("journal_entries") or []),
            "expand_request": dict(expand_request or {}),
        }
    )


def apply_runtime_state_to_plan(plan: TaskPlan, runtime_state: SubTaskRuntimeState) -> None:
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
            subtask.execution_brief = restore_execution_brief(runtime_state.execution_brief)
        return


def build_dispatch_summary(plan: TaskPlan, runtime_states: list[SubTaskRuntimeState]) -> dict[str, Any]:
    for runtime_state in runtime_states:
        apply_runtime_state_to_plan(plan, runtime_state)
    total = len(plan.subtasks)
    completed = sum(1 for subtask in plan.subtasks if subtask.status == SubTaskStatus.COMPLETED)
    no_data = sum(1 for subtask in plan.subtasks if subtask.status == SubTaskStatus.NO_DATA)
    expanded = sum(1 for subtask in plan.subtasks if subtask.status == SubTaskStatus.EXPANDED)
    business_failure = sum(1 for subtask in plan.subtasks if subtask.status == SubTaskStatus.BUSINESS_FAILURE)
    system_failure = sum(1 for subtask in plan.subtasks if subtask.status == SubTaskStatus.SYSTEM_FAILURE)
    skipped = sum(1 for subtask in plan.subtasks if subtask.status == SubTaskStatus.SKIPPED)
    total_collected = sum(
        int(subtask.collected_count or 0) for subtask in plan.subtasks if subtask.status == SubTaskStatus.COMPLETED
    )
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
