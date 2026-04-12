from __future__ import annotations

import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autospider.graph.state_access import dispatch_summary, select_summary, task_plan


def test_dispatch_summary_reads_root_dispatch_result() -> None:
    state = {
        "dispatch": {"summary": {}},
        "dispatch_result": {"total": 4, "completed": 4, "failed": 0, "total_collected": 36},
        "summary": {"merged_items": 31},
    }

    assert dispatch_summary(state) == {
        "total": 4,
        "completed": 4,
        "failed": 0,
        "total_collected": 36,
    }


def test_select_summary_merges_dispatch_and_result_metrics() -> None:
    state = {
        "dispatch": {"summary": {}},
        "dispatch_result": {"total": 4, "completed": 4, "failed": 0, "total_collected": 36},
        "result": {"summary": {"merged_items": 31, "unique_urls": 31}},
        "summary": {"thread_id": "thread-1", "entry_mode": "chat_pipeline"},
    }

    assert select_summary(state) == {
        "total": 4,
        "completed": 4,
        "failed": 0,
        "total_collected": 36,
        "merged_items": 31,
        "unique_urls": 31,
        "thread_id": "thread-1",
        "entry_mode": "chat_pipeline",
    }


def test_dispatch_summary_merges_dispatch_result_and_dispatch_summary() -> None:
    state = {
        "dispatch_result": {"total": 4, "completed": 3},
        "dispatch": {
            "dispatch_result": {"failed": 1},
            "summary": {"total_collected": 36},
        },
    }

    assert dispatch_summary(state) == {
        "total": 4,
        "completed": 3,
        "failed": 1,
        "total_collected": 36,
    }


def test_task_plan_preserves_legacy_planning_state_via_workflow_adapter() -> None:
    state = {
        "planning": {"task_plan": {"steps": ["clarify", "dispatch"]}},
        "dispatch": {"task_plan": {"steps": ["dispatch-only"]}},
    }

    assert task_plan(state) == {"steps": ["dispatch-only"]}


def test_task_plan_keeps_empty_dispatch_dict_without_falling_back() -> None:
    state = {
        "dispatch": {"task_plan": {}},
        "task_plan": {"steps": ["root-plan"]},
        "planning": {"task_plan": {"steps": ["planning-plan"]}},
    }

    assert task_plan(state) == {}


def test_task_plan_keeps_empty_dispatch_list_without_falling_back() -> None:
    state = {
        "dispatch": {"task_plan": []},
        "task_plan": {"steps": ["root-plan"]},
        "planning": {"task_plan": {"steps": ["planning-plan"]}},
    }

    assert task_plan(state) == []
