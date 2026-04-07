"""Pipeline execution service."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable

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

    async def execute(self, *, params: dict[str, Any], thread_id: str) -> dict[str, Any]:
        result = await self._run_pipeline(
            list_url=str(params.get("list_url") or ""),
            task_description=str(params.get("task_description") or ""),
            fields=self._field_factory(list(params.get("fields") or [])),
            output_dir=str(params.get("output_dir") or "output"),
            headless=bool(params.get("headless", False)),
            explore_count=params.get("field_explore_count"),
            validate_count=params.get("field_validate_count"),
            consumer_concurrency=params.get("consumer_concurrency"),
            max_pages=params.get("max_pages"),
            target_url_count=params.get("target_url_count"),
            pipeline_mode=params.get("pipeline_mode"),
            guard_intervention_mode="interrupt",
            guard_thread_id=thread_id,
            selected_skills=list(params.get("selected_skills") or []),
            plan_knowledge=str(params.get("plan_knowledge") or ""),
            task_plan_snapshot=dict(params.get("task_plan_snapshot") or {}),
            plan_journal=list(params.get("plan_journal") or []),
            initial_nav_steps=list(params.get("initial_nav_steps") or []),
            anchor_url=params.get("anchor_url"),
            page_state_signature=str(params.get("page_state_signature") or ""),
            variant_label=params.get("variant_label"),
        )

        summary_file = Path(str(params.get("output_dir") or "output")) / "pipeline_summary.json"
        pipeline_result = {
            "total_urls": int(result.get("total_urls", 0) or 0),
            "success_count": int(result.get("success_count", 0) or 0),
            "failed_count": int(result.get("failed_count", 0) or 0),
            "success_rate": float(result.get("success_rate", 0.0) or 0.0),
            "required_field_success_rate": float(
                result.get("required_field_success_rate", 0.0) or 0.0
            ),
            "validation_failure_count": int(result.get("validation_failure_count", 0) or 0),
            "execution_state": str(result.get("execution_state") or ""),
            "outcome_state": str(result.get("outcome_state") or ""),
            "promotion_state": str(result.get("promotion_state") or ""),
            "items_file": str(result.get("items_file", "")),
            "summary_file": str(summary_file),
            "execution_id": str(result.get("execution_id", "")),
        }
        artifacts: list[dict[str, str]] = []
        if result.get("items_file"):
            artifacts.append(self._artifact_builder("pipeline_items", str(result["items_file"])))
        artifacts.append(self._artifact_builder("pipeline_summary", summary_file))
        return {
            "pipeline_result": pipeline_result,
            "summary": {
                "total_urls": pipeline_result["total_urls"],
                "success_count": pipeline_result["success_count"],
                "failed_count": pipeline_result["failed_count"],
                "success_rate": pipeline_result["success_rate"],
                "required_field_success_rate": pipeline_result["required_field_success_rate"],
                "validation_failure_count": pipeline_result["validation_failure_count"],
                "execution_state": pipeline_result["execution_state"],
                "outcome_state": pipeline_result["outcome_state"],
                "promotion_state": pipeline_result["promotion_state"],
                "execution_id": pipeline_result["execution_id"],
                "items_file": pipeline_result["items_file"],
            },
            "artifacts": artifacts,
            "result": pipeline_result,
        }
