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
    """合并所有子任务的采集结果。

    该类负责遍历任务计划中的所有已完成子任务，读取其对应的结果文件，
    进行去重处理后，合并为一个全局的 JSONL 文件，并生成统计摘要。
    """

    def aggregate(self, plan: TaskPlan, output_dir: str) -> dict:
        """合并结果并生成汇总。

        Args:
            plan: 任务计划（包含各子任务状态和执行元数据）。
            output_dir: 根输出目录，子任务结果存储在该目录下。

        Returns:
            dict: 包含汇总信息（如总条数、唯一 URL 数、子任务详情等）的字典。
        """
        all_items: list[dict] = []
        seen_urls: set[str] = set()
        subtask_stats: list[dict] = []

        # 遍历所有子任务
        for subtask in plan.subtasks:
            # 仅处理状态为 COMPLETED 的子任务
            if subtask.status != SubTaskStatus.COMPLETED:
                continue

            # 子任务的结果通常存储在以 subtask_ID 命名的子目录下
            subtask_dir = Path(output_dir) / f"subtask_{subtask.id}"
            items_count = 0

            # 查找该子任务产出的所有提取项文件 (JSONL 格式)
            for jsonl_file in subtask_dir.glob("pipeline_extracted_items_*.jsonl"):
                try:
                    # 逐行读取并解析
                    for line in jsonl_file.read_text(encoding="utf-8").splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        item = json.loads(line)
                        url = item.get("url", "")

                        # 全局 URL 去重，防止不同子任务采集到重复页面
                        if url and url in seen_urls:
                            continue
                        if url:
                            seen_urls.add(url)

                        # 在每条数据中注入来源子任务的元信息，方便回溯
                        item["_subtask_id"] = subtask.id
                        item["_subtask_name"] = subtask.name
                        all_items.append(item)
                        items_count += 1
                except Exception as e:
                    logger.warning(
                        "[Aggregator] 读取 %s 失败: %s", jsonl_file, e
                    )

            # 记录该子任务的统计数据
            subtask_stats.append({
                "id": subtask.id,
                "name": subtask.name,
                "items": items_count,
            })

        # 写入合并后的全量结果文件
        output_path = Path(output_dir)
        merged_file = output_path / "merged_results.jsonl"
        output_path.mkdir(parents=True, exist_ok=True)

        with open(merged_file, "w", encoding="utf-8") as f:
            for item in all_items:
                # 依然保持每行一个 JSON 对象的 JSONL 格式
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

        # 构建并写入全局汇总信息 (JSON 格式)
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
