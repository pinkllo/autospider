"""Pure builders for pipeline runtime and finalization contexts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .finalization import PipelineFinalizationContext, build_execution_id
from .orchestration import PipelineRuntimeContext, PipelineSessionBundle

if TYPE_CHECKING:
    from autospider.contexts.collection.domain.fields import FieldDefinition
    from autospider.contexts.collection.infrastructure.channel.base import URLChannel
    from autospider.contexts.experience.application.use_cases.skill_runtime import SkillRuntime
    from .progress_tracker import TaskProgressTracker
    from .types import ExecutionContext


@dataclass(frozen=True, slots=True)
class PipelineRunResolved:
    list_url: str
    task_description: str
    execution_brief: dict[str, Any]
    fields: list["FieldDefinition"]
    output_dir: str
    headless: bool | None
    explore_count: int
    validate_count: int
    max_pages: int | None
    target_url_count: int | None
    guard_intervention_mode: str
    guard_thread_id: str
    anchor_url: str | None
    page_state_signature: str
    variant_label: str | None
    output_path: Path
    items_path: Path
    summary_path: Path
    staging_items_path: Path
    staging_summary_path: Path
    consumer_workers: int
    execution_id: str
    is_resume: bool


def _resolve_execution_id(context: "ExecutionContext", fields: list["FieldDefinition"]) -> str:
    execution_id = str(context.execution_id or "").strip()
    if execution_id:
        return execution_id

    request = context.request
    return build_execution_id(
        list_url=request.list_url,
        task_description=request.task_description,
        execution_brief=dict(request.execution_brief or {}),
        fields=fields,
        target_url_count=request.target_url_count,
        max_pages=request.max_pages,
        pipeline_mode=context.pipeline_mode.value,
        thread_id=request.guard_thread_id,
        page_state_signature=context.identity.page_state_signature,
        anchor_url=context.identity.anchor_url or None,
        variant_label=context.identity.variant_label or None,
    )


def resolve_pipeline_run(
    context: "ExecutionContext",
    *,
    explore_count_default: int,
    validate_count_default: int,
) -> PipelineRunResolved:
    request = context.request
    fields = list(context.fields)
    output_path = Path(request.output_dir)
    execution_id = _resolve_execution_id(context, fields)
    explore_count = request.field_explore_count
    validate_count = request.field_validate_count
    return PipelineRunResolved(
        list_url=request.list_url,
        task_description=request.task_description,
        execution_brief=dict(request.execution_brief or {}),
        fields=fields,
        output_dir=request.output_dir,
        headless=request.headless,
        explore_count=explore_count_default if explore_count is None else explore_count,
        validate_count=validate_count_default if validate_count is None else validate_count,
        max_pages=request.max_pages,
        target_url_count=request.target_url_count,
        guard_intervention_mode=request.guard_intervention_mode,
        guard_thread_id=request.guard_thread_id,
        anchor_url=context.identity.anchor_url or None,
        page_state_signature=context.identity.page_state_signature,
        variant_label=context.identity.variant_label or None,
        output_path=output_path,
        items_path=output_path / "pipeline_extracted_items.jsonl",
        summary_path=output_path / "pipeline_summary.json",
        staging_items_path=output_path / "pipeline_extracted_items.next.jsonl",
        staging_summary_path=output_path / "pipeline_summary.next.json",
        consumer_workers=int(context.consumer_concurrency or 1),
        execution_id=execution_id,
        is_resume=context.resume_mode.value == "resume",
    )


def build_pipeline_summary(resolved: PipelineRunResolved) -> dict[str, Any]:
    return {
        "run_id": resolved.execution_id,
        "list_url": resolved.list_url,
        "anchor_url": str(resolved.anchor_url or ""),
        "page_state_signature": str(resolved.page_state_signature or ""),
        "variant_label": str(resolved.variant_label or ""),
        "task_description": resolved.task_description,
        "mode": "",
        "total_urls": 0,
        "success_count": 0,
        "failed_count": 0,
        "consumer_concurrency": resolved.consumer_workers,
        "target_url_count": resolved.target_url_count,
        "items_file": str(resolved.items_path),
        "summary_file": str(resolved.summary_path),
        "execution_id": resolved.execution_id,
        "durability_state": "staged",
        "durably_persisted": False,
        "terminal_reason": "",
    }


def build_runtime_context(
    context: "ExecutionContext",
    *,
    resolved: PipelineRunResolved,
    channel: "URLChannel",
    run_records: dict[str, dict[str, Any]],
    summary: dict[str, Any],
    tracker: "TaskProgressTracker",
    skill_runtime: "SkillRuntime",
    sessions: PipelineSessionBundle,
) -> PipelineRuntimeContext:
    return PipelineRuntimeContext(
        list_url=resolved.list_url,
        anchor_url=resolved.anchor_url,
        page_state_signature=resolved.page_state_signature,
        variant_label=resolved.variant_label,
        task_description=resolved.task_description,
        execution_brief=dict(resolved.execution_brief or {}),
        fields=resolved.fields,
        output_dir=resolved.output_dir,
        headless=resolved.headless,
        explore_count=resolved.explore_count,
        validate_count=resolved.validate_count,
        consumer_workers=resolved.consumer_workers,
        max_pages=resolved.max_pages,
        target_url_count=resolved.target_url_count,
        guard_intervention_mode=resolved.guard_intervention_mode,
        guard_thread_id=resolved.guard_thread_id,
        selected_skills=list(context.selected_skills),
        channel=channel,
        run_records=run_records,
        summary=summary,
        tracker=tracker,
        skill_runtime=skill_runtime,
        sessions=sessions,
        plan_knowledge=context.plan_knowledge,
        task_plan_snapshot=dict(context.task_plan_snapshot or {}),
        plan_journal=list(context.plan_journal or []),
        initial_nav_steps=list(context.initial_nav_steps or []),
        decision_context=dict(context.decision_context or {}),
        world_snapshot=dict(context.world_snapshot or {}),
        failure_records=tuple(list(context.failure_records or ())),
        url_only_mode=len(resolved.fields) == 0,
        execution_id=resolved.execution_id,
        resume_mode="resume" if resolved.is_resume else "fresh",
        global_browser_budget=context.global_browser_budget,
    )


def _build_failure_records(records: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    return [dict(item) for item in list(records or ())]


def _build_site_profile_snapshot(world_snapshot: dict[str, Any]) -> dict[str, Any]:
    return dict(dict(world_snapshot or {}).get("site_profile") or {})


def _build_failure_patterns(world_snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    return list(dict(world_snapshot or {}).get("failure_patterns") or [])


def build_finalization_context(
    context: "ExecutionContext",
    *,
    resolved: PipelineRunResolved,
    summary: dict[str, Any],
    runtime_context: PipelineRuntimeContext,
    sessions: PipelineSessionBundle,
    committed_records: dict[str, dict[str, Any]],
) -> PipelineFinalizationContext:
    world_snapshot = dict(runtime_context.world_snapshot or {})
    return PipelineFinalizationContext(
        list_url=resolved.list_url,
        anchor_url=resolved.anchor_url,
        page_state_signature=resolved.page_state_signature,
        variant_label=resolved.variant_label,
        task_description=resolved.task_description,
        semantic_signature=str(context.identity.semantic_signature or ""),
        strategy_payload=dict(context.identity.strategy_payload or {}),
        execution_brief=dict(resolved.execution_brief or {}),
        fields=resolved.fields,
        thread_id=resolved.guard_thread_id,
        output_dir=resolved.output_dir,
        output_path=resolved.output_path,
        items_path=resolved.items_path,
        summary_path=resolved.summary_path,
        staging_items_path=resolved.staging_items_path,
        staging_summary_path=resolved.staging_summary_path,
        committed_records=committed_records,
        summary=summary,
        runtime_state=runtime_context.runtime_state,
        plan_knowledge=runtime_context.plan_knowledge,
        task_plan=dict(runtime_context.task_plan_snapshot or {}),
        plan_journal=list(runtime_context.plan_journal or []),
        tracker=runtime_context.tracker,
        sessions=sessions,
        world_snapshot=world_snapshot,
        site_profile_snapshot=_build_site_profile_snapshot(world_snapshot),
        failure_records=_build_failure_records(runtime_context.failure_records),
        failure_patterns=_build_failure_patterns(world_snapshot),
    )
