"""Pipeline execution service."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable

from ..contracts import ExecutionRequest, PipelineRunSummary
from ..pipeline import run_pipeline as default_run_pipeline
from .service_utils import build_artifact, build_field_definitions


class PipelineExecutionService:
    """Application-facing wrapper around the pipeline runner."""

    def __init__(
        self,
        *,
        run_pipeline: Callable[..., Awaitable[dict[str, Any]]] = default_run_pipeline,
        field_factory: Callable[[list[dict[str, Any]]], list[Any]] = build_field_definitions,
        artifact_builder: Callable[[str, str | Path], dict[str, str]] = build_artifact,
    ) -> None:
        self._run_pipeline = run_pipeline
        self._field_factory = field_factory
        self._artifact_builder = artifact_builder

    async def execute(self, *, request: ExecutionRequest) -> dict[str, Any]:
        result = await self._run_pipeline(
            list_url=request.list_url,
            task_description=request.task_description,
            fields=self._field_factory(list(request.fields or [])),
            output_dir=request.output_dir,
            headless=request.headless,
            explore_count=request.field_explore_count,
            validate_count=request.field_validate_count,
            consumer_concurrency=request.consumer_concurrency,
            max_pages=request.max_pages,
            target_url_count=request.target_url_count,
            pipeline_mode=request.pipeline_mode,
            guard_intervention_mode=request.guard_intervention_mode,
            guard_thread_id=request.guard_thread_id,
            selected_skills=list(request.selected_skills or []),
            plan_knowledge=request.plan_knowledge,
            task_plan_snapshot=dict(request.task_plan_snapshot or {}),
            plan_journal=list(request.plan_journal or []),
            initial_nav_steps=list(request.initial_nav_steps or []),
            anchor_url=request.anchor_url,
            page_state_signature=request.page_state_signature,
            variant_label=request.variant_label,
        )

        summary_file = Path(request.output_dir) / "pipeline_summary.json"
        pipeline_result = PipelineRunSummary.from_raw(result, summary_file=str(summary_file))
        artifacts: list[dict[str, str]] = []
        if pipeline_result.items_file:
            artifacts.append(self._artifact_builder("pipeline_items", pipeline_result.items_file))
        artifacts.append(self._artifact_builder("pipeline_summary", summary_file))
        pipeline_payload = pipeline_result.model_dump(mode="python")
        return {
            "pipeline_result": pipeline_payload,
            "summary": {
                "total_urls": pipeline_result.total_urls,
                "success_count": pipeline_result.success_count,
                "failed_count": pipeline_result.failed_count,
                "success_rate": pipeline_result.success_rate,
                "required_field_success_rate": pipeline_result.required_field_success_rate,
                "validation_failure_count": pipeline_result.validation_failure_count,
                "execution_state": pipeline_result.execution_state,
                "outcome_state": pipeline_result.outcome_state,
                "promotion_state": pipeline_result.promotion_state.value,
                "execution_id": pipeline_result.execution_id,
                "items_file": pipeline_result.items_file,
                "durably_persisted": pipeline_result.durably_persisted,
            },
            "artifacts": artifacts,
            "result": pipeline_payload,
        }
