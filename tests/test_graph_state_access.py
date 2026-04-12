from __future__ import annotations

import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autospider.graph.state_access import (
    collection_config,
    dispatch_summary,
    get_error_state,
    request_params,
    select_summary,
    subtask_results,
    task_plan,
)


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


def test_get_error_state_ignores_root_error_without_code() -> None:
    state = {
        "error": {"message": "root-only-message"},
        "node_error": {"code": "NODE", "message": "node-message"},
        "error_code": "ROOT_CODE",
        "error_message": "root-code-message",
    }

    assert get_error_state(state) == {"code": "NODE", "message": "node-message"}


def test_get_error_state_keeps_explicit_empty_result_final_error() -> None:
    state = {
        "result": {"final_error": {}},
        "node_error": {"code": "NODE", "message": "node-message"},
        "error_code": "ROOT",
    }

    assert get_error_state(state) == {}


def test_request_params_keeps_explicit_empty_workflow_namespace() -> None:
    state = {
        "world": {"request_params": {}},
        "normalized_params": {"keyword": "legacy"},
    }

    assert request_params(state) == {}


def test_collection_config_keeps_explicit_empty_workflow_namespace() -> None:
    state = {
        "world": {"collection_config": {}},
        "result": {"data": {"collection_config": {"source": "legacy"}}},
    }

    assert collection_config(state) == {}


def test_dispatch_summary_keeps_explicit_empty_workflow_namespace() -> None:
    state = {
        "execution": {"dispatch_summary": {}},
        "dispatch_result": {"total": 4},
        "dispatch": {"summary": {"failed": 1}},
    }

    assert dispatch_summary(state) == {}


def test_subtask_results_keeps_explicit_empty_workflow_namespace() -> None:
    state = {
        "execution": {"subtask_results": []},
        "dispatch": {"subtask_results": [{"id": "dispatch"}]},
        "subtask_results": [{"id": "root"}],
    }

    assert subtask_results(state) == []
