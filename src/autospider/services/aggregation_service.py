"""Result aggregation service."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..contracts import AggregationReport, ExecutionRequest
from ..domain.planning import TaskPlan
from ..pipeline.aggregator import ResultAggregator
from .service_utils import build_artifact


class AggregationService:
    """Aggregates subtask outputs after dispatch completes."""

    def __init__(
        self,
        *,
        aggregator_cls: type = ResultAggregator,
        artifact_builder: Callable[[str, str | Path], dict[str, str]] = build_artifact,
    ) -> None:
        self._aggregator_cls = aggregator_cls
        self._artifact_builder = artifact_builder

    def execute(
        self,
        *,
        request: ExecutionRequest,
        task_plan: TaskPlan,
    ) -> dict[str, Any]:
        aggregate_result = AggregationReport.model_validate(self._aggregator_cls().aggregate(
            plan=task_plan,
            output_dir=request.output_dir,
        ))
        output_dir = Path(request.output_dir)
        report = aggregate_result.model_dump(mode="python")
        return {
            "aggregate_result": report,
            "summary": {
                "merged_items": aggregate_result.merged_items,
                "unique_urls": aggregate_result.unique_urls,
                "eligible_subtasks": aggregate_result.eligible_subtasks,
                "excluded_subtasks": aggregate_result.excluded_subtasks,
                "failed_subtasks": aggregate_result.failed_subtasks,
            },
            "result": report,
            "artifacts": [
                self._artifact_builder("merged_results", output_dir / "merged_results.jsonl"),
                self._artifact_builder("merged_summary", output_dir / "merged_summary.json"),
            ],
        }
