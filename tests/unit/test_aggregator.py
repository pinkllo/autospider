"""ResultAggregator 单元测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from autospider.common.types import SubTask, SubTaskStatus, TaskPlan
from autospider.contracts import AggregationFailure
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


def _mark_aggregate_ready(subtask: SubTask, result_file: Path) -> None:
    subtask.result_file = str(result_file)
    subtask.context = {
        "durably_persisted": True,
        "reliable_for_aggregation": True,
    }


class TestAggregator:
    def test_merge_two_subtasks(self, tmp_path):
        st1 = _make_subtask("01")
        st2 = _make_subtask("02")
        file1 = tmp_path / "subtask_01" / "pipeline_extracted_items.jsonl"
        file2 = tmp_path / "subtask_02" / "pipeline_extracted_items.jsonl"
        _mark_aggregate_ready(st1, file1)
        _mark_aggregate_ready(st2, file2)
        plan = _make_plan([st1, st2])

        _write_jsonl(
            file1,
            [
                {"url": "https://example.com/a", "title": "A"},
                {"url": "https://example.com/b", "title": "B"},
            ],
        )
        _write_jsonl(file2, [{"url": "https://example.com/c", "title": "C"}])

        result = ResultAggregator().aggregate(plan=plan, output_dir=str(tmp_path))

        assert result["merged_items"] == 3
        assert result["unique_urls"] == 3
        assert result["eligible_subtasks"] == 2
        assert result["failed_subtasks"] == 0

    def test_dedup_urls(self, tmp_path):
        st1 = _make_subtask("01")
        st2 = _make_subtask("02")
        file1 = tmp_path / "subtask_01" / "pipeline_extracted_items.jsonl"
        file2 = tmp_path / "subtask_02" / "pipeline_extracted_items.jsonl"
        _mark_aggregate_ready(st1, file1)
        _mark_aggregate_ready(st2, file2)
        plan = _make_plan([st1, st2])

        _write_jsonl(file1, [{"url": "https://example.com/dup", "title": "From ST1"}])
        _write_jsonl(file2, [{"url": "https://example.com/dup", "title": "From ST2"}])

        result = ResultAggregator().aggregate(plan=plan, output_dir=str(tmp_path))

        assert result["merged_items"] == 1
        assert result["unique_urls"] == 1

    def test_excludes_failed_subtasks_from_report(self, tmp_path):
        st1 = _make_subtask("01", status=SubTaskStatus.COMPLETED)
        st2 = _make_subtask("02", status=SubTaskStatus.FAILED)
        file1 = tmp_path / "subtask_01" / "pipeline_extracted_items.jsonl"
        _mark_aggregate_ready(st1, file1)
        plan = _make_plan([st1, st2])

        _write_jsonl(file1, [{"url": "https://example.com/a", "title": "A"}])
        result = ResultAggregator().aggregate(plan=plan, output_dir=str(tmp_path))

        assert result["merged_items"] == 1
        assert result["excluded_subtasks"] == 1
        excluded = [item for item in result["subtask_details"] if item["eligibility"] == "excluded"]
        assert excluded[0]["reason"] == "status_failed"

    def test_strictly_fails_when_result_file_missing(self, tmp_path):
        st = _make_subtask("01")
        missing_file = tmp_path / "subtask_01" / "pipeline_extracted_items.jsonl"
        _mark_aggregate_ready(st, missing_file)
        plan = _make_plan([st])

        with pytest.raises(AggregationFailure) as exc_info:
            ResultAggregator().aggregate(plan=plan, output_dir=str(tmp_path))

        report = exc_info.value.report.model_dump(mode="python")
        assert report["failed_subtasks"] == 1
        assert report["failure_reasons"] == ["01:result_file_missing"]

    def test_strictly_fails_when_jsonl_is_invalid(self, tmp_path):
        st = _make_subtask("01")
        result_file = tmp_path / "subtask_01" / "pipeline_extracted_items.jsonl"
        _mark_aggregate_ready(st, result_file)
        plan = _make_plan([st])
        result_file.parent.mkdir(parents=True, exist_ok=True)
        result_file.write_text("{bad json}\n", encoding="utf-8")

        with pytest.raises(AggregationFailure) as exc_info:
            ResultAggregator().aggregate(plan=plan, output_dir=str(tmp_path))

        report = exc_info.value.report.model_dump(mode="python")
        assert report["failed_subtasks"] == 1
        assert "invalid_jsonl_line" in report["failure_reasons"][0]

    def test_excludes_completed_but_non_durable_subtasks(self, tmp_path):
        st = _make_subtask("01")
        st.result_file = str(tmp_path / "subtask_01" / "pipeline_extracted_items.jsonl")
        st.context = {
            "durably_persisted": False,
            "reliable_for_aggregation": True,
        }
        plan = _make_plan([st])

        result = ResultAggregator().aggregate(plan=plan, output_dir=str(tmp_path))

        assert result["merged_items"] == 0
        assert result["eligible_subtasks"] == 0
        assert result["excluded_subtasks"] == 1
        assert result["subtask_details"][0]["reason"] == "subtask_not_durable"
