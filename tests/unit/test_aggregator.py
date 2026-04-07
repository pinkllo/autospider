"""ResultAggregator 单元测试。"""

from __future__ import annotations

import json
import pytest
from pathlib import Path

from autospider.common.types import SubTask, SubTaskStatus, TaskPlan
from autospider.pipeline.aggregator import ResultAggregator


def _make_plan(subtasks: list[SubTask]) -> TaskPlan:
    return TaskPlan(
        plan_id="test_plan",
        original_request="测试需求",
        site_url="https://example.com",
        subtasks=subtasks,
        total_subtasks=len(subtasks),
    )


def _make_subtask(id: str, status: SubTaskStatus = SubTaskStatus.COMPLETED) -> SubTask:
    return SubTask(
        id=id,
        name=f"分类_{id}",
        list_url=f"https://example.com/{id}",
        task_description=f"采集分类 {id}",
        status=status,
    )


def _write_jsonl(path: Path, items: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


class TestAggregator:
    """ResultAggregator 基础测试。"""

    def test_merge_two_subtasks(self, tmp_path):
        """合并两个子任务的结果。"""
        st1 = _make_subtask("01")
        st2 = _make_subtask("02")
        plan = _make_plan([st1, st2])

        # 创建子任务输出
        _write_jsonl(
            tmp_path / "subtask_01" / "pipeline_extracted_items_run1.jsonl",
            [
                {"url": "https://example.com/a", "title": "A"},
                {"url": "https://example.com/b", "title": "B"},
            ],
        )
        _write_jsonl(
            tmp_path / "subtask_02" / "pipeline_extracted_items_run2.jsonl",
            [
                {"url": "https://example.com/c", "title": "C"},
            ],
        )

        aggregator = ResultAggregator()
        result = aggregator.aggregate(plan=plan, output_dir=str(tmp_path))

        assert result["total_items"] == 3
        assert result["unique_urls"] == 3
        assert result["subtasks_completed"] == 2

        # 检查合并文件
        merged = tmp_path / "merged_results.jsonl"
        assert merged.exists()
        lines = merged.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 3

        # 检查子任务来源标记
        first_item = json.loads(lines[0])
        assert "_subtask_id" in first_item
        assert "_subtask_name" in first_item

    def test_dedup_urls(self, tmp_path):
        """重复 URL 应被去重。"""
        st1 = _make_subtask("01")
        st2 = _make_subtask("02")
        plan = _make_plan([st1, st2])

        _write_jsonl(
            tmp_path / "subtask_01" / "pipeline_extracted_items_run1.jsonl",
            [{"url": "https://example.com/dup", "title": "From ST1"}],
        )
        _write_jsonl(
            tmp_path / "subtask_02" / "pipeline_extracted_items_run2.jsonl",
            [{"url": "https://example.com/dup", "title": "From ST2"}],
        )

        aggregator = ResultAggregator()
        result = aggregator.aggregate(plan=plan, output_dir=str(tmp_path))

        assert result["total_items"] == 1
        assert result["unique_urls"] == 1

    def test_skip_failed_subtasks(self, tmp_path):
        """失败的子任务不应被包含。"""
        st1 = _make_subtask("01", status=SubTaskStatus.COMPLETED)
        st2 = _make_subtask("02", status=SubTaskStatus.FAILED)
        plan = _make_plan([st1, st2])

        _write_jsonl(
            tmp_path / "subtask_01" / "pipeline_extracted_items_run1.jsonl",
            [{"url": "https://example.com/a", "title": "A"}],
        )

        aggregator = ResultAggregator()
        result = aggregator.aggregate(plan=plan, output_dir=str(tmp_path))

        assert result["total_items"] == 1
        assert result["subtasks_completed"] == 1

    def test_empty_plan(self, tmp_path):
        """空计划应返回空结果。"""
        plan = _make_plan([])

        aggregator = ResultAggregator()
        result = aggregator.aggregate(plan=plan, output_dir=str(tmp_path))

        assert result["total_items"] == 0
        assert result["unique_urls"] == 0


    def test_prefer_explicit_result_file_over_stale_history(self, tmp_path):
        """显式 result_file 应覆盖目录里的历史结果文件。"""
        current_file = tmp_path / "subtask_01" / "pipeline_extracted_items.jsonl"
        stale_file = tmp_path / "subtask_01" / "pipeline_extracted_items_old.jsonl"

        st = _make_subtask("01")
        st.result_file = str(current_file)
        plan = _make_plan([st])

        _write_jsonl(current_file, [{"url": "https://example.com/current", "title": "Current"}])
        _write_jsonl(stale_file, [{"url": "https://example.com/stale", "title": "Stale"}])

        aggregator = ResultAggregator()
        result = aggregator.aggregate(plan=plan, output_dir=str(tmp_path))

        assert result["total_items"] == 1
        merged = tmp_path / "merged_results.jsonl"
        lines = merged.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        assert json.loads(lines[0])["url"] == "https://example.com/current"

    def test_skip_unreliable_completed_subtask(self, tmp_path):
        st = _make_subtask("01")
        st.context = {"reliable_for_aggregation": False}
        plan = _make_plan([st])

        _write_jsonl(
            tmp_path / "subtask_01" / "pipeline_extracted_items_run1.jsonl",
            [{"url": "https://example.com/a", "title": "A"}],
        )

        aggregator = ResultAggregator()
        result = aggregator.aggregate(plan=plan, output_dir=str(tmp_path))

        assert result["total_items"] == 0
        assert result["subtasks_completed"] == 0
        assert result["subtasks_skipped_unreliable"] == 1

        """应生成汇总文件。"""
        st = _make_subtask("01")
        plan = _make_plan([st])

        _write_jsonl(
            tmp_path / "subtask_01" / "pipeline_extracted_items_run1.jsonl",
            [{"url": "https://example.com/a", "title": "A"}],
        )

        aggregator = ResultAggregator()
        aggregator.aggregate(plan=plan, output_dir=str(tmp_path))

        summary_file = tmp_path / "merged_summary.json"
        assert summary_file.exists()

        summary = json.loads(summary_file.read_text(encoding="utf-8"))
        assert summary["total_items"] == 1
