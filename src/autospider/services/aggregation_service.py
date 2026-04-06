"""Result aggregation service."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from ..common.experience import SkillSedimenter
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

    def _sediment_site_skill(
        self,
        *,
        params: dict[str, Any],
        task_plan: TaskPlan,
        subtask_results: list[dict[str, Any]],
        plan_knowledge: str,
    ) -> Path | None:
        effective_results = [
            result
            for result in subtask_results
            if str(result.get("summary", {}).get("promotion_state") or "").strip().lower() == "reusable"
        ]
        if not effective_results:
            return None

        sedimenter = SkillSedimenter()
        fields = list(getattr(task_plan, "shared_fields", []) or [])
        return sedimenter.sediment_from_subtask_results(
            list_url=str(params.get("list_url") or task_plan.site_url or ""),
            task_description=str(params.get("task_description") or task_plan.original_request or ""),
            fields=fields,
            subtask_results=effective_results,
            plan_knowledge=plan_knowledge,
            overwrite_existing=False,
            source="aggregated_run",
        )

    def execute(
        self,
        *,
        params: dict[str, Any],
        task_plan: TaskPlan,
        dispatch_result: dict[str, Any] | None = None,
        subtask_results: list[dict[str, Any]] | None = None,
        plan_knowledge: str = "",
    ) -> dict[str, Any]:
        aggregate_result = self._aggregator_cls().aggregate(
            plan=task_plan,
            output_dir=str(params.get("output_dir") or "output"),
        )
        sedimented_skill = self._sediment_site_skill(
            params=params,
            task_plan=task_plan,
            subtask_results=list(subtask_results or []),
            plan_knowledge=plan_knowledge,
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
                *(
                    [self._artifact_builder("site_skill", sedimented_skill)]
                    if sedimented_skill
                    else []
                ),
            ],
        }

    def run(
        self,
        *,
        plan: TaskPlan,
        output_dir: str,
        dispatch_result: dict[str, Any] | None = None,
        subtask_results: list[dict[str, Any]] | None = None,
        plan_knowledge: str = "",
    ) -> dict[str, Any]:
        return self.execute(
            params={"output_dir": output_dir},
            task_plan=plan,
            dispatch_result=dispatch_result,
            subtask_results=subtask_results,
            plan_knowledge=plan_knowledge,
        )
