"""结果聚合器，负责严格合并可靠且可追溯的子任务结果。"""

from __future__ import annotations

import json
from pathlib import Path

from ..common.logger import get_logger
from ..common.storage.idempotent_io import write_json_idempotent, write_text_if_changed
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
        if subtask.status != SubTaskStatus.COMPLETED:
            return AggregationEligibility.EXCLUDED, f"status_{subtask.status.value}"
        summary = dict(getattr(subtask, "context", {}) or {})
        if not summary:
            return AggregationEligibility.EXCLUDED, "missing_subtask_context"
        if not bool(summary.get("durably_persisted")):
            return AggregationEligibility.EXCLUDED, "subtask_not_durable"
        if not bool(summary.get("reliable_for_aggregation")):
            return AggregationEligibility.EXCLUDED, "subtask_not_reliable"
        result_file = str(subtask.result_file or "").strip()
        if not result_file:
            return AggregationEligibility.FAILED, "missing_result_file"
        return AggregationEligibility.INCLUDED, ""

    @staticmethod
    def _read_result_items(jsonl_file: Path) -> list[dict]:
        payload = jsonl_file.read_text(encoding="utf-8")
        items: list[dict] = []
        for lineno, line in enumerate(payload.splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                items.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"invalid_jsonl_line:{jsonl_file}:{lineno}:{exc}") from exc
        return items

    def aggregate(self, plan: TaskPlan, output_dir: str) -> dict:
        all_items: list[dict] = []
        seen_urls: set[str] = set()
        details: list[AggregationSubtaskDetail] = []
        failure_reasons: list[str] = []

        for subtask in plan.subtasks:
            eligibility, reason = self._resolve_eligibility(subtask)
            detail = AggregationSubtaskDetail(
                id=subtask.id,
                name=subtask.name,
                status=subtask.status.value,
                eligibility=eligibility,
                reason=reason,
                items=0,
                result_file=str(subtask.result_file or ""),
            )
            if eligibility != AggregationEligibility.INCLUDED:
                details.append(detail)
                if eligibility == AggregationEligibility.FAILED:
                    failure_reasons.append(f"{subtask.id}:{reason}")
                continue

            jsonl_file = Path(str(subtask.result_file or "")).expanduser()
            if not jsonl_file.exists():
                detail.eligibility = AggregationEligibility.FAILED
                detail.reason = "result_file_missing"
                details.append(detail)
                failure_reasons.append(f"{subtask.id}:result_file_missing")
                continue

            try:
                items = self._read_result_items(jsonl_file)
            except Exception as exc:  # noqa: BLE001
                detail.eligibility = AggregationEligibility.FAILED
                detail.reason = str(exc)
                details.append(detail)
                failure_reasons.append(f"{subtask.id}:{exc}")
                continue

            for item in items:
                url = str(item.get("url") or "")
                if url and url in seen_urls:
                    continue
                if url:
                    seen_urls.add(url)
                normalized = dict(item)
                normalized["_subtask_id"] = subtask.id
                normalized["_subtask_name"] = subtask.name
                all_items.append(normalized)
                detail.items += 1
            details.append(detail)

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        merged_file = output_path / "merged_results.jsonl"
        summary_file = output_path / "merged_summary.json"

        report = AggregationReport(
            merged_items=len(all_items),
            unique_urls=len(seen_urls),
            eligible_subtasks=sum(1 for detail in details if detail.eligibility == AggregationEligibility.INCLUDED),
            excluded_subtasks=sum(1 for detail in details if detail.eligibility == AggregationEligibility.EXCLUDED),
            failed_subtasks=sum(1 for detail in details if detail.eligibility == AggregationEligibility.FAILED),
            failure_reasons=failure_reasons,
            subtask_details=details,
            merged_file=str(merged_file),
            summary_file=str(summary_file),
        )

        if failure_reasons:
            raise AggregationFailure(report)

        merged_payload = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in all_items)
        write_text_if_changed(merged_file, merged_payload)
        write_json_idempotent(summary_file, report.model_dump(mode="python"), volatile_keys=set())
        logger.info(
            "[Aggregator] 合并完成: %d 条记录 (%d 个唯一 URL), %d 个可聚合子任务",
            report.merged_items,
            report.unique_urls,
            report.eligible_subtasks,
        )
        return report.model_dump(mode="python")
