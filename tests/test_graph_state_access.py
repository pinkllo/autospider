from __future__ import annotations

import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autospider.contexts.planning.domain import (
    ExecutionBrief,
    PlanJournalEntry,
    PlanNode,
    PlanNodeType,
    SubTask,
    SubTaskMode,
    TaskPlan,
)
from autospider.composition.legacy.graph.nodes.capability_nodes import build_planning_runtime_payload
from autospider.composition.legacy.graph.state_access import (
    collection_config,
    dispatch_summary,
    get_error_state,
    request_params,
    select_summary,
    subtask_results,
    task_plan,
)


def test_dispatch_summary_reads_only_execution_namespace() -> None:
    state = {
        "execution": {
            "dispatch_summary": {"total": 4, "completed": 4, "failed": 0, "total_collected": 36}
        },
        "dispatch_result": {"total": 99},
    }

    assert dispatch_summary(state) == {
        "total": 4,
        "completed": 4,
        "failed": 0,
        "total_collected": 36,
    }


def test_select_summary_merges_execution_and_result_metrics() -> None:
    state = {
        "execution": {
            "dispatch_summary": {"total": 4, "completed": 4, "failed": 0, "total_collected": 36}
        },
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
    }


def test_dispatch_summary_ignores_legacy_dispatch_result_when_execution_missing() -> None:
    state = {
        "dispatch_result": {"total": 4, "completed": 3},
        "dispatch": {
            "dispatch_result": {"failed": 1},
            "summary": {"total_collected": 36},
        },
    }

    assert dispatch_summary(state) == {}


def test_task_plan_reads_only_control_namespace() -> None:
    state = {
        "control": {"task_plan": {"steps": ["workflow-dispatch"]}},
        "planning": {"task_plan": {"steps": ["clarify", "dispatch"]}},
        "dispatch": {"task_plan": {"steps": ["dispatch-only"]}},
    }

    assert task_plan(state) == {"steps": ["workflow-dispatch"]}


def test_task_plan_keeps_explicit_empty_control_dict_without_falling_back() -> None:
    state = {
        "control": {"task_plan": {}},
        "dispatch": {"task_plan": {"steps": ["dispatch-plan"]}},
        "task_plan": {"steps": ["root-plan"]},
        "planning": {"task_plan": {"steps": ["planning-plan"]}},
    }

    assert task_plan(state) == {}


def test_task_plan_keeps_explicit_empty_control_list_without_falling_back() -> None:
    state = {
        "control": {"task_plan": []},
        "dispatch": {"task_plan": {"steps": ["dispatch-plan"]}},
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


def test_get_stage_status_reads_workflow_control_stage_status() -> None:
    state = {
        "control": {"stage_status": "ok"},
        "planning": {"status": "fatal"},
        "dispatch": {"status": "fatal"},
    }

    from autospider.composition.legacy.graph.state_access import get_stage_status

    assert get_stage_status(state) == "ok"


def test_request_params_reads_planner_runtime_payload_from_world_namespace() -> None:
    plan = TaskPlan(
        plan_id="plan_001",
        original_request="采集采购公告",
        site_url="https://example.com",
        subtasks=[
            SubTask(
                id="leaf_001",
                name="采购公告",
                list_url="https://example.com/notices/purchase",
                anchor_url="https://example.com/notices",
                page_state_signature="sig-purchase",
                task_description="采集采购公告详情页",
                mode=SubTaskMode.COLLECT,
                execution_brief=ExecutionBrief(objective="收集采购公告详情页链接"),
                plan_node_id="node_002",
            )
        ],
        nodes=[
            PlanNode(
                node_id="node_001",
                name="招标公告",
                node_type=PlanNodeType.CATEGORY,
                url="https://example.com/notices",
                task_description="进入招标公告列表",
                observations="入口页识别为分类页",
                children_count=1,
            )
        ],
        journal=[
            PlanJournalEntry(
                entry_id="journal_0001",
                node_id="node_001",
                phase="planning",
                action="analyze_page",
                reason="入口页识别为分类页",
                evidence="存在多个公告类型入口",
                metadata={},
                created_at="2026-04-12T10:00:00",
            )
        ],
        total_subtasks=1,
        shared_fields=[{"name": "title", "description": "公告标题"}],
        created_at="2026-04-12T10:00:00",
        updated_at="2026-04-12T10:00:01",
    )
    payload = build_planning_runtime_payload(
        plan=plan,
        plan_knowledge="structured planning knowledge",
        request_params={
            "list_url": "https://example.com/notices",
            "target_url_count": 8,
            "max_concurrent": 2,
        },
    )

    params = request_params(
        {
            "world": payload["world"],
            "control": payload["control"],
            "normalized_params": {"legacy": True},
        }
    )

    assert params["plan_knowledge"] == "structured planning knowledge"
    assert params["world_snapshot"] == payload["world"]
    assert params["control_snapshot"] == payload["control"]
    assert params["decision_context"]["current_plan"]["goal"] == "进入招标公告列表"
