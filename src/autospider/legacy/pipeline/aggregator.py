"""结果聚合器，负责严格合并可靠且可追溯的子任务结果。"""

from __future__ import annotations

import json
from pathlib import Path

from autospider.platform.persistence.sql.orm.engine import session_scope
from autospider.platform.persistence.sql.orm.repositories import TaskRepository
from autospider.platform.observability.logger import get_logger
from autospider.platform.persistence.files.idempotent_io import write_json_idempotent
from .types import (
    AggregationEligibility,
    AggregationFailure,
    AggregationReport,
    AggregationSubtaskDetail,
)
from ...contexts.planning.domain import SubTask, SubTaskStatus, TaskPlan
from ..domain.runtime import SubTaskRuntimeState

logger = get_logger(__name__)

EXCLUDED_SUBTASK_STATUSES = frozenset({SubTaskStatus.NO_DATA})


class ResultAggregator:
    """合并所有子任务的采集结果。"""

    @staticmethod
    def _should_raise(report: AggregationReport) -> bool:
        return bool(report.failure_reasons) and report.eligible_subtasks <= 0

    @staticmethod
    def _resolve_eligibility(
        subtask: SubTask,
        runtime_state: SubTaskRuntimeState | None,
    ) -> tuple[AggregationEligibility, str]:
        if runtime_state is None:
            return AggregationEligibility.FAILED, "missing_runtime_state"
        if subtask.status in EXCLUDED_SUBTASK_STATUSES:
            return AggregationEligibility.EXCLUDED, f"status_{subtask.status.value}"
        if subtask.status != SubTaskStatus.COMPLETED:
            return AggregationEligibility.FAILED, f"status_{subtask.status.value}"
        summary = runtime_state.summary
        if str(summary.durability_state or "").strip().lower() != "durable":
            return AggregationEligibility.FAILED, "subtask_not_durable"
        if not bool(summary.reliable_for_aggregation):
            return AggregationEligibility.FAILED, "subtask_not_reliable"
        execution_id = str(summary.execution_id or "").strip()
        if not execution_id:
            return AggregationEligibility.FAILED, "missing_execution_id"
        return AggregationEligibility.INCLUDED, ""

    @staticmethod
    def _load_execution_items(execution_id: str) -> list[dict]:
        with session_scope() as session:
            return TaskRepository(session).list_eligible_items_by_execution(execution_id)

    @staticmethod
    def _included_detail_ids(details: list[AggregationSubtaskDetail]) -> set[str]:
        return {
            detail.id for detail in details if detail.eligibility == AggregationEligibility.INCLUDED
        }

    @staticmethod
    def _runtime_state_map(
        subtask_results: list[SubTaskRuntimeState] | None,
    ) -> dict[str, SubTaskRuntimeState]:
        return {state.subtask_id: state for state in list(subtask_results or [])}

    def aggregate(
        self,
        plan: TaskPlan,
        output_dir: str,
        subtask_results: list[SubTaskRuntimeState] | None = None,
    ) -> dict:
        seen_urls: set[str] = set()
        details: list[AggregationSubtaskDetail] = []
        failure_reasons: list[str] = []
        conflict_count = 0
        runtime_state_map = self._runtime_state_map(subtask_results)

        for subtask in plan.subtasks:
            runtime_state = runtime_state_map.get(subtask.id)
            eligibility, reason = self._resolve_eligibility(subtask, runtime_state)
            detail = AggregationSubtaskDetail(
                id=subtask.id,
                name=subtask.name,
                status=subtask.status.value,
                eligibility=eligibility,
                reason=reason,
                excluded_reason=reason if eligibility == AggregationEligibility.EXCLUDED else "",
                items=0,
                result_file=str(subtask.result_file or ""),
                conflict_count=0,
            )
            if eligibility != AggregationEligibility.INCLUDED:
                details.append(detail)
                if eligibility == AggregationEligibility.FAILED:
                    failure_reasons.append(f"{subtask.id}:{reason}")
                continue

            execution_id = str(runtime_state.summary.execution_id if runtime_state else "").strip()
            if not execution_id:
                detail.eligibility = AggregationEligibility.FAILED
                detail.reason = "missing_execution_id"
                details.append(detail)
                failure_reasons.append(f"{subtask.id}:missing_execution_id")
                continue

            try:
                eligible_items = self._load_execution_items(execution_id)
            except Exception as exc:  # noqa: BLE001
                detail.eligibility = AggregationEligibility.FAILED
                detail.reason = str(exc)
                details.append(detail)
                failure_reasons.append(f"{subtask.id}:{exc}")
                continue
            if not eligible_items:
                detail.eligibility = AggregationEligibility.FAILED
                detail.reason = "missing_durable_items"
                details.append(detail)
                failure_reasons.append(f"{subtask.id}:missing_durable_items")
                continue
            details.append(detail)

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        merged_file = output_path / "merged_results.jsonl"
        summary_file = output_path / "merged_summary.json"
        if merged_file.exists():
            merged_file.unlink()

        with merged_file.open("w", encoding="utf-8") as handle:
            merged_items = 0
            included_ids = self._included_detail_ids(details)
            for subtask in plan.subtasks:
                if subtask.id not in included_ids:
                    continue
                detail = next(item for item in details if item.id == subtask.id)
                runtime_state = runtime_state_map.get(subtask.id)
                execution_id = str(
                    runtime_state.summary.execution_id if runtime_state else ""
                ).strip()
                items = self._load_execution_items(execution_id)
                for item in items:
                    payload = dict(item.get("item") or {})
                    url = str(item.get("url") or payload.get("url") or "")
                    if url and url in seen_urls:
                        detail.conflict_count += 1
                        conflict_count += 1
                        continue
                    if url:
                        seen_urls.add(url)
                    normalized = dict(payload)
                    normalized.setdefault("url", url)
                    normalized["_subtask_id"] = subtask.id
                    normalized["_subtask_name"] = subtask.name
                    handle.write(json.dumps(normalized, ensure_ascii=False) + "\n")
                    detail.items += 1
                    merged_items += 1

        report = AggregationReport(
            merged_items=merged_items,
            unique_urls=len(seen_urls),
            eligible_subtasks=sum(
                1 for detail in details if detail.eligibility == AggregationEligibility.INCLUDED
            ),
            excluded_subtasks=sum(
                1 for detail in details if detail.eligibility == AggregationEligibility.EXCLUDED
            ),
            failed_subtasks=sum(
                1 for detail in details if detail.eligibility == AggregationEligibility.FAILED
            ),
            conflict_count=conflict_count,
            failure_reasons=failure_reasons,
            subtask_details=details,
            merged_file=str(merged_file),
            summary_file=str(summary_file),
        )

        if self._should_raise(report):
            raise AggregationFailure(report)
        serialized = report.model_dump(mode="json")
        write_json_idempotent(summary_file, serialized, volatile_keys=set())
        if failure_reasons:
            logger.warning(
                "[Aggregator] 部分子任务未参与合并: %s",
                ", ".join(report.failure_reasons),
            )
        logger.info(
            "[Aggregator] 合并完成: %d 条记录 (%d 个唯一 URL), %d 个可聚合子任务",
            report.merged_items,
            report.unique_urls,
            report.eligible_subtasks,
        )
        return serialized
