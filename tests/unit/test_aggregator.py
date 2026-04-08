"""ResultAggregator 单元测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from autospider.domain.planning import SubTask, SubTaskStatus, TaskPlan
from autospider.domain.runtime import SubTaskRuntimeState
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


def _runtime_state(subtask: SubTask, execution_id: str, *, durable: bool = True) -> dict:
    return SubTaskRuntimeState(
        subtask_id=subtask.id,
        name=subtask.name,
        list_url=subtask.list_url,
        task_description=subtask.task_description,
        status=subtask.status.value,
        summary={
            "durability_state": "durable" if durable else "staged",
            "durably_persisted": durable,
            "reliable_for_aggregation": durable,
            "execution_id": execution_id,
        },
    ).model_dump(mode="python")


class TestAggregator:
    def test_merge_two_subtasks(self, tmp_path):
        st1 = _make_subtask("01")
        st2 = _make_subtask("02")
        plan = _make_plan([st1, st2])
        aggregator = ResultAggregator()
        aggregator._load_execution_items = lambda execution_id: {  # type: ignore[method-assign]
            "exec_01": [
                {"url": "https://example.com/a", "item": {"url": "https://example.com/a", "title": "A"}},
                {"url": "https://example.com/b", "item": {"url": "https://example.com/b", "title": "B"}},
            ],
            "exec_02": [
                {"url": "https://example.com/c", "item": {"url": "https://example.com/c", "title": "C"}}
            ],
        }[execution_id]
        result = aggregator.aggregate(
            plan=plan,
            output_dir=str(tmp_path),
            subtask_results=[_runtime_state(st1, "exec_01"), _runtime_state(st2, "exec_02")],
        )

        assert result["merged_items"] == 3
        assert result["unique_urls"] == 3
        assert result["eligible_subtasks"] == 2
        assert result["failed_subtasks"] == 0

    def test_dedup_urls(self, tmp_path):
        st1 = _make_subtask("01")
        st2 = _make_subtask("02")
        plan = _make_plan([st1, st2])
        aggregator = ResultAggregator()
        aggregator._load_execution_items = lambda execution_id: {  # type: ignore[method-assign]
            "exec_01": [{"url": "https://example.com/dup", "item": {"url": "https://example.com/dup", "title": "From ST1"}}],
            "exec_02": [{"url": "https://example.com/dup", "item": {"url": "https://example.com/dup", "title": "From ST2"}}],
        }[execution_id]
        result = aggregator.aggregate(
            plan=plan,
            output_dir=str(tmp_path),
            subtask_results=[_runtime_state(st1, "exec_01"), _runtime_state(st2, "exec_02")],
        )

        assert result["merged_items"] == 1
        assert result["unique_urls"] == 1
        assert result["conflict_count"] == 1

    def test_excludes_failed_subtasks_from_report(self, tmp_path):
        st1 = _make_subtask("01", status=SubTaskStatus.COMPLETED)
        st2 = _make_subtask("02", status=SubTaskStatus.SYSTEM_FAILURE)
        plan = _make_plan([st1, st2])
        aggregator = ResultAggregator()
        aggregator._load_execution_items = lambda execution_id: [  # type: ignore[method-assign]
            {"url": "https://example.com/a", "item": {"url": "https://example.com/a", "title": "A"}}
        ]
        with pytest.raises(AggregationFailure) as exc_info:
            aggregator.aggregate(
                plan=plan,
                output_dir=str(tmp_path),
                subtask_results=[_runtime_state(st1, "exec_01"), _runtime_state(st2, "exec_02")],
            )

        report = exc_info.value.report.model_dump(mode="python")
        assert report["failed_subtasks"] == 1
        assert report["failure_reasons"] == ["02:status_system_failure"]

    def test_excludes_completed_but_non_durable_subtasks(self, tmp_path):
        st = _make_subtask("01")
        plan = _make_plan([st])

        with pytest.raises(AggregationFailure) as exc_info:
            ResultAggregator().aggregate(
                plan=plan,
                output_dir=str(tmp_path),
                subtask_results=[_runtime_state(st, "exec_01", durable=False)],
            )

        report = exc_info.value.report.model_dump(mode="python")
        assert report["merged_items"] == 0
        assert report["eligible_subtasks"] == 0
        assert report["failed_subtasks"] == 1
        assert report["subtask_details"][0]["reason"] == "subtask_not_durable"

    def test_excludes_no_data_subtasks_without_failing_aggregation(self, tmp_path):
        st1 = _make_subtask("01", status=SubTaskStatus.COMPLETED)
        st2 = _make_subtask("02", status=SubTaskStatus.NO_DATA)
        plan = _make_plan([st1, st2])
        aggregator = ResultAggregator()
        aggregator._load_execution_items = lambda execution_id: {  # type: ignore[method-assign]
            "exec_01": [
                {"url": "https://example.com/a", "item": {"url": "https://example.com/a", "title": "A"}}
            ],
            "exec_02": [],
        }[execution_id]

        result = aggregator.aggregate(
            plan=plan,
            output_dir=str(tmp_path),
            subtask_results=[_runtime_state(st1, "exec_01"), _runtime_state(st2, "exec_02")],
        )

        assert result["merged_items"] == 1
        assert result["eligible_subtasks"] == 1
        assert result["excluded_subtasks"] == 1
        assert result["failed_subtasks"] == 0
        assert result["failure_reasons"] == []
        assert result["subtask_details"][1]["eligibility"] == "excluded"
        assert result["subtask_details"][1]["reason"] == "status_no_data"

    def test_all_no_data_subtasks_return_empty_report_without_failure(self, tmp_path):
        st = _make_subtask("01", status=SubTaskStatus.NO_DATA)
        plan = _make_plan([st])

        result = ResultAggregator().aggregate(
            plan=plan,
            output_dir=str(tmp_path),
            subtask_results=[_runtime_state(st, "exec_01")],
        )

        assert result["merged_items"] == 0
        assert result["eligible_subtasks"] == 0
        assert result["excluded_subtasks"] == 1
        assert result["failed_subtasks"] == 0
        assert result["failure_reasons"] == []
        assert result["subtask_details"][0]["reason"] == "status_no_data"
