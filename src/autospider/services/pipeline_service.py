"""Pipeline execution service."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable

from ..contracts import ExecutionContext, ExecutionRequest, PipelineRunSummary
from ..pipeline import run_pipeline as default_run_pipeline
from .service_utils import build_artifact, build_execution_context, build_field_definitions


class PipelineExecutionService:
    """Application-facing wrapper around the pipeline runner."""

    def __init__(
        self,
        *,
        run_pipeline: Callable[[ExecutionContext], Awaitable[dict[str, Any]]] = default_run_pipeline,
        field_factory: Callable[[list[dict[str, Any]]], list[Any]] = build_field_definitions,
        artifact_builder: Callable[[str, str | Path], dict[str, str]] = build_artifact,
        context_builder: Callable[..., ExecutionContext] = build_execution_context,
    ) -> None:
        self._run_pipeline = run_pipeline
        self._field_factory = field_factory
        self._artifact_builder = artifact_builder
        self._context_builder = context_builder

    async def execute(self, *, request: ExecutionRequest) -> dict[str, Any]:
        field_definitions = self._field_factory(list(request.fields or []))
        context = self._context_builder(request, fields=field_definitions)
        result = await self._run_pipeline(context)

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
                "terminal_reason": pipeline_result.terminal_reason,
                "promotion_state": pipeline_result.promotion_state.value,
                "execution_id": pipeline_result.execution_id,
                "items_file": pipeline_result.items_file,
                "durability_state": pipeline_result.durability_state.value,
                "durably_persisted": pipeline_result.durably_persisted,
            },
            "artifacts": artifacts,
            "result": pipeline_payload,
        }
