"""结果聚合器 — 合并所有子任务的采集结果。

负责将多个子任务的 JSONL 结果文件合并为一个，
并执行 URL 去重和生成全局汇总报告。
"""

from __future__ import annotations

import json
from pathlib import Path

from ..common.logger import get_logger
from ..common.types import SubTaskStatus, TaskPlan

logger = get_logger(__name__)


class ResultAggregator:
    """合并所有子任务的采集结果。"""

    def aggregate(self, plan: TaskPlan, output_dir: str) -> dict:
        """合并结果并生成汇总。

        Args:
            plan: 任务计划（包含各子任务状态）。
            output_dir: 根输出目录。

        Returns:
            汇总信息字典。
        """
        all_items: list[dict] = []
        seen_urls: set[str] = set()
        subtask_stats: list[dict] = []

        for subtask in plan.subtasks:
            if subtask.status != SubTaskStatus.COMPLETED:
                continue

            subtask_dir = Path(output_dir) / f"subtask_{subtask.id}"
            items_count = 0

            for jsonl_file in subtask_dir.glob("pipeline_extracted_items_*.jsonl"):
                try:
                    for line in jsonl_file.read_text(encoding="utf-8").splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        item = json.loads(line)
                        url = item.get("url", "")

                        # URL 去重
                        if url and url in seen_urls:
                            continue
                        if url:
                            seen_urls.add(url)

                        item["_subtask_id"] = subtask.id
                        item["_subtask_name"] = subtask.name
                        all_items.append(item)
                        items_count += 1
                except Exception as e:
                    logger.warning(
                        "[Aggregator] 读取 %s 失败: %s", jsonl_file, e
                    )

            subtask_stats.append({
                "id": subtask.id,
                "name": subtask.name,
                "items": items_count,
            })

        # 写入合并结果
        output_path = Path(output_dir)
        merged_file = output_path / "merged_results.jsonl"
        output_path.mkdir(parents=True, exist_ok=True)

        with open(merged_file, "w", encoding="utf-8") as f:
            for item in all_items:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

        # 写入汇总
        summary = {
            "total_items": len(all_items),
            "unique_urls": len(seen_urls),
            "subtasks_completed": len(subtask_stats),
            "subtasks_total": len(plan.subtasks),
            "subtask_details": subtask_stats,
            "merged_file": str(merged_file),
        }

        summary_file = output_path / "merged_summary.json"
        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        logger.info(
            "[Aggregator] 合并完成: %d 条记录 (%d 个唯一 URL), 来自 %d 个子任务",
            len(all_items),
            len(seen_urls),
            len(subtask_stats),
        )

        return summary
