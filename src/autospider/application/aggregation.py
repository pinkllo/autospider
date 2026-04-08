"""聚合 use case。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from ..contracts import AggregationReport, ExecutionContext
from ..domain.planning import TaskPlan
from ..pipeline.aggregator import ResultAggregator
from .helpers import build_artifact


class AggregateResultsUseCase:
    """调度结束后的结果聚合入口。"""

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
        context: ExecutionContext,
        task_plan: TaskPlan,
        subtask_results: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        aggregate_result = AggregationReport.model_validate(
            self._aggregator_cls().aggregate(
                plan=task_plan,
                output_dir=context.request.output_dir,
                subtask_results=list(subtask_results or []),
            )
        )
        output_dir = Path(context.request.output_dir)
        report = aggregate_result.model_dump(mode="python")
        return {
            "data": {"aggregate_result": report},
            "summary": {
                "merged_items": aggregate_result.merged_items,
                "unique_urls": aggregate_result.unique_urls,
                "eligible_subtasks": aggregate_result.eligible_subtasks,
                "excluded_subtasks": aggregate_result.excluded_subtasks,
                "failed_subtasks": aggregate_result.failed_subtasks,
                "conflict_count": aggregate_result.conflict_count,
            },
            "artifacts": [
                self._artifact_builder("merged_results", output_dir / "merged_results.jsonl"),
                self._artifact_builder("merged_summary", output_dir / "merged_summary.json"),
            ],
        }
