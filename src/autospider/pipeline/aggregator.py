"""结果聚合器 — 合并所有子任务的采集结果。

负责将多个子任务的 JSONL 结果文件合并为一个，
并执行 URL 去重和生成全局汇总报告。
"""

from __future__ import annotations

import json
from pathlib import Path

from ..common.logger import get_logger
from ..common.storage.idempotent_io import write_json_idempotent, write_text_if_changed
from ..domain.planning import SubTask, SubTaskStatus, TaskPlan

logger = get_logger(__name__)


class ResultAggregator:
    """合并所有子任务的采集结果。"""

    def aggregate(self, plan: TaskPlan, output_dir: str) -> dict:
        """合并结果并生成汇总。"""
        all_items: list[dict] = []
        seen_urls: set[str] = set()
        subtask_stats: list[dict] = []

        for subtask in plan.subtasks:
            if subtask.status != SubTaskStatus.COMPLETED:
                continue

            items_count = 0
            for jsonl_file in self._resolve_result_files(subtask=subtask, output_dir=output_dir):
                try:
                    for line in jsonl_file.read_text(encoding="utf-8").splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        item = json.loads(line)
                        url = item.get("url", "")

                        if url and url in seen_urls:
                            continue
                        if url:
                            seen_urls.add(url)

                        item["_subtask_id"] = subtask.id
                        item["_subtask_name"] = subtask.name
                        all_items.append(item)
                        items_count += 1
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[Aggregator] 读取 %s 失败: %s", jsonl_file, exc)

            subtask_stats.append({
                "id": subtask.id,
                "name": subtask.name,
                "items": items_count,
            })

        output_path = Path(output_dir)
        merged_file = output_path / "merged_results.jsonl"
        output_path.mkdir(parents=True, exist_ok=True)

        merged_payload = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in all_items)
        write_text_if_changed(merged_file, merged_payload)

        summary = {
            "total_items": len(all_items),
            "unique_urls": len(seen_urls),
            "subtasks_completed": len(subtask_stats),
            "subtasks_total": len(plan.subtasks),
            "subtask_details": subtask_stats,
            "merged_file": str(merged_file),
        }

        summary_file = output_path / "merged_summary.json"
        write_json_idempotent(summary_file, summary, volatile_keys=set())

        logger.info(
            "[Aggregator] 合并完成: %d 条记录 (%d 个唯一 URL), 来自 %d 个子任务",
            len(all_items),
            len(seen_urls),
            len(subtask_stats),
        )

        return summary

    def _resolve_result_files(self, *, subtask: SubTask, output_dir: str) -> list[Path]:
        explicit = Path(str(subtask.result_file or "")).expanduser() if subtask.result_file else None
        if explicit and explicit.exists():
            return [explicit]

        subtask_dir = Path(output_dir) / f"subtask_{subtask.id}"
        stable_file = subtask_dir / "pipeline_extracted_items.jsonl"
        if stable_file.exists():
            return [stable_file]

        return sorted(subtask_dir.glob("pipeline_extracted_items_*.jsonl"))
