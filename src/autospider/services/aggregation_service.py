"""Result aggregation service."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

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
        params: dict[str, Any],
        task_plan: TaskPlan,
        dispatch_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        aggregate_result = self._aggregator_cls().aggregate(
            plan=task_plan,
            output_dir=str(params.get("output_dir") or "output"),
        )
        summary = dict(dispatch_result or {})
        summary.update(
            {
                "merged_items": aggregate_result.get("total_items", 0),
                "unique_urls": aggregate_result.get("unique_urls", 0),
            }
        )
        output_dir = Path(str(params.get("output_dir") or "output"))
        return {
            "aggregate_result": aggregate_result,
            "summary": summary,
            "result": {"aggregate_result": aggregate_result, "dispatch_result": summary},
            "artifacts": [
                self._artifact_builder("merged_results", output_dir / "merged_results.jsonl"),
                self._artifact_builder("merged_summary", output_dir / "merged_summary.json"),
            ],
        }

    def run(self, *, plan: TaskPlan, output_dir: str, dispatch_result: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.execute(
            params={"output_dir": output_dir},
            task_plan=plan,
            dispatch_result=dispatch_result,
        )
