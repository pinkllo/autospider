"""结果聚合器，负责严格合并可靠且可追溯的子任务结果。"""

from __future__ import annotations

import json
from pathlib import Path

from ..common.db.engine import session_scope
from ..common.db.repositories import TaskRepository
from ..common.logger import get_logger
from ..common.storage.idempotent_io import write_json_idempotent
from ..contracts import (
    AggregationEligibility,
    AggregationFailure,
    AggregationReport,
    AggregationSubtaskDetail,
)
from ..domain.planning import SubTask, SubTaskStatus, TaskPlan

logger = get_logger(__name__)


class ResultAggregator:
    """合并所有子任务的采集结果。"""

    @staticmethod
    def _resolve_eligibility(subtask: SubTask) -> tuple[AggregationEligibility, str]:
        summary = dict(getattr(subtask, "context", {}) or {})
        if subtask.status != SubTaskStatus.COMPLETED:
            return AggregationEligibility.FAILED, f"status_{subtask.status.value}"
        if not summary:
            return AggregationEligibility.FAILED, "missing_subtask_context"
        if str(summary.get("durability_state") or "").strip().lower() != "durable":
            return AggregationEligibility.FAILED, "subtask_not_durable"
        if not bool(summary.get("reliable_for_aggregation")):
            return AggregationEligibility.FAILED, "subtask_not_reliable"
        execution_id = str(summary.get("execution_id") or "").strip()
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
            detail.id
            for detail in details
            if detail.eligibility == AggregationEligibility.INCLUDED
        }

    def aggregate(self, plan: TaskPlan, output_dir: str) -> dict:
        seen_urls: set[str] = set()
        details: list[AggregationSubtaskDetail] = []
        failure_reasons: list[str] = []
        conflict_count = 0

        for subtask in plan.subtasks:
            eligibility, reason = self._resolve_eligibility(subtask)
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

            execution_id = str(getattr(subtask, "context", {}).get("execution_id") or "").strip()
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
                execution_id = str(getattr(subtask, "context", {}).get("execution_id") or "").strip()
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
            eligible_subtasks=sum(1 for detail in details if detail.eligibility == AggregationEligibility.INCLUDED),
            excluded_subtasks=sum(1 for detail in details if detail.eligibility == AggregationEligibility.EXCLUDED),
            failed_subtasks=sum(1 for detail in details if detail.eligibility == AggregationEligibility.FAILED),
            conflict_count=conflict_count,
            failure_reasons=failure_reasons,
            subtask_details=details,
            merged_file=str(merged_file),
            summary_file=str(summary_file),
        )

        if failure_reasons:
            raise AggregationFailure(report)
        write_json_idempotent(summary_file, report.model_dump(mode="python"), volatile_keys=set())
        logger.info(
            "[Aggregator] 合并完成: %d 条记录 (%d 个唯一 URL), %d 个可聚合子任务",
            report.merged_items,
            report.unique_urls,
            report.eligible_subtasks,
        )
        return report.model_dump(mode="python")
