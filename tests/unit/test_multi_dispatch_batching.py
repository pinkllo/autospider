from __future__ import annotations

from autospider.common.config import config
from autospider.domain.planning import ExecutionBrief, SubTask, SubTaskMode, SubTaskStatus, TaskPlan
from autospider.graph.subgraphs.multi_dispatch import (
    _build_subtask_result,
    _build_dispatch_summary,
    _inherit_parent_nav_steps,
    _resolve_runtime_replan_max_children,
    _resolve_runtime_subtasks_use_main_model,
    _subtask_signature,
    merge_dispatch_round,
    prepare_dispatch_batch,
)
from autospider.pipeline.finalization import build_execution_id
from autospider.pipeline.worker import SubTaskWorker


def test_prepare_dispatch_batch_respects_max_concurrent():
    result = prepare_dispatch_batch(
        {
            "normalized_params": {"max_concurrent": 2},
            "dispatch_queue": [
                {"id": "sub_01"},
                {"id": "sub_02"},
                {"id": "sub_03"},
            ],
            "spawned_subtasks": [{"id": "old_spawn"}],
        }
    )

    assert result["current_batch"] == [{"id": "sub_01"}, {"id": "sub_02"}]
    assert result["dispatch_queue"] == [{"id": "sub_03"}]
    assert result["spawned_subtasks"] == []


def test_runtime_replan_limits_default_to_config():
    assert _resolve_runtime_replan_max_children({}) == int(
        getattr(config.planner, "runtime_subtasks_max_children", 0)
    )
    assert _resolve_runtime_subtasks_use_main_model({}) is bool(
        getattr(config.planner, "runtime_subtasks_use_main_model", False)
    )


def test_runtime_replan_limits_accept_overrides():
    assert _resolve_runtime_replan_max_children({"runtime_subtask_max_children": "3"}) == 3
    assert _resolve_runtime_subtasks_use_main_model({"runtime_subtasks_use_main_model": "false"}) is False


def test_inherit_parent_nav_steps_fills_missing_nav_chain():
    plan = TaskPlan(
        plan_id="plan_1",
        original_request="采集公告",
        site_url="https://example.com",
        subtasks=[
            SubTask(
                id="parent_1",
                name="公告",
                list_url="https://example.com/list",
                task_description="采集公告",
                nav_steps=[{"action": "click", "target_text": "公告"}],
            )
        ],
    )

    payload = _inherit_parent_nav_steps(
        {
            "id": "child_1",
            "parent_id": "parent_1",
            "name": "子分类",
            "list_url": "https://example.com/list",
            "task_description": "采集子分类",
        },
        plan,
    )

    assert payload["nav_steps"] == [{"action": "click", "target_text": "公告"}]


def test_subtask_signature_prefers_page_state_signature():
    sig = _subtask_signature(
        {
            "name": "工程建设",
            "list_url": "https://example.com/list",
            "task_description": "采集工程建设",
            "page_state_signature": "state_a",
        }
    )

    assert sig == ("state", "state_a", "")


def test_build_subtask_result_keeps_state_identity_fields():
    subtask = SubTask(
        id="leaf_001",
        name="工程建设",
        list_url="https://example.com/list",
        anchor_url="https://example.com/root",
        page_state_signature="state_a",
        variant_label="工程建设",
        task_description="采集工程建设",
    )

    result = _build_subtask_result(subtask, status=subtask.status, result={"total_urls": 3})

    assert result["anchor_url"] == "https://example.com/root"
    assert result["page_state_signature"] == "state_a"
    assert result["variant_label"] == "工程建设"


def test_build_execution_id_distinguishes_same_url_different_state():
    exec_a = build_execution_id(
        list_url="https://example.com/list",
        task_description="采集公告",
        fields=[],
        target_url_count=10,
        max_pages=2,
        pipeline_mode="memory",
        thread_id="",
        page_state_signature="state_a",
        anchor_url="https://example.com/root",
        variant_label="工程建设",
    )
    exec_b = build_execution_id(
        list_url="https://example.com/list",
        task_description="采集公告",
        fields=[],
        target_url_count=10,
        max_pages=2,
        pipeline_mode="memory",
        thread_id="",
        page_state_signature="state_b",
        anchor_url="https://example.com/root",
        variant_label="土地矿业",
    )

    assert exec_a != exec_b


def test_build_execution_id_distinguishes_same_url_different_execution_brief():
    exec_a = build_execution_id(
        list_url="https://example.com/list",
        task_description="采集公告",
        execution_brief={"current_scope": "工程建设"},
        fields=[],
        target_url_count=10,
        max_pages=2,
        pipeline_mode="memory",
        thread_id="",
    )
    exec_b = build_execution_id(
        list_url="https://example.com/list",
        task_description="采集公告",
        execution_brief={"current_scope": "土地矿业"},
        fields=[],
        target_url_count=10,
        max_pages=2,
        pipeline_mode="memory",
        thread_id="",
    )

    assert exec_a != exec_b


def test_worker_run_namespace_distinguishes_same_url_different_state():
    subtask_a = SubTask(
        id="leaf_001",
        name="工程建设",
        list_url="https://example.com/list",
        page_state_signature="state_a",
        task_description="采集公告",
    )
    subtask_b = SubTask(
        id="leaf_002",
        name="土地矿业",
        list_url="https://example.com/list",
        page_state_signature="state_b",
        task_description="采集公告",
    )

    worker_a = SubTaskWorker(subtask=subtask_a, fields=[])
    worker_b = SubTaskWorker(subtask=subtask_b, fields=[])

    assert worker_a._build_run_namespace() != worker_b._build_run_namespace()


def test_build_dispatch_summary_counts_expanded_tasks():
    expanded = SubTask(
        id="expand_001",
        name="工程建设",
        list_url="https://example.com/list",
        task_description="继续拆分工程建设",
        mode=SubTaskMode.EXPAND,
        execution_brief=ExecutionBrief(current_scope="工程建设"),
        status=SubTaskStatus.EXPANDED,
    )
    completed = SubTask(
        id="leaf_001",
        name="交通运输工程",
        list_url="https://example.com/list",
        task_description="采集交通运输工程",
        collected_count=3,
        status=SubTaskStatus.COMPLETED,
    )
    plan = TaskPlan(
        plan_id="plan_1",
        original_request="采集分类项目",
        site_url="https://example.com",
        subtasks=[expanded, completed],
    )

    summary = _build_dispatch_summary(plan, [])

    assert summary["expanded"] == 1
    assert summary["completed"] == 1
    assert summary["failed"] == 0
    assert summary["total_collected"] == 3


def test_merge_dispatch_round_preserves_pending_queue_and_appends_runtime_children(monkeypatch):
    parent = SubTask(
        id="expand_parent",
        name="工程建设",
        list_url="https://example.com/list",
        task_description="继续拆分工程建设",
        mode=SubTaskMode.EXPAND,
        execution_brief=ExecutionBrief(current_scope="工程建设"),
    )
    pending = SubTask(
        id="expand_pending",
        name="土地矿业",
        list_url="https://example.com/list",
        task_description="继续拆分土地矿业",
        mode=SubTaskMode.EXPAND,
        execution_brief=ExecutionBrief(current_scope="土地矿业"),
    )
    child = SubTask(
        id="expand_child",
        name="交通运输工程",
        list_url="https://example.com/list",
        task_description="继续拆分交通运输工程",
        parent_id=parent.id,
        depth=2,
        mode=SubTaskMode.EXPAND,
        execution_brief=ExecutionBrief(
            parent_chain=["工程建设"],
            current_scope="交通运输工程",
        ),
    )
    plan = TaskPlan(
        plan_id="plan_1",
        original_request="采集分类项目",
        site_url="https://example.com",
        subtasks=[parent, pending],
        journal=[],
    )
    result_item = _build_subtask_result(
        parent,
        status=SubTaskStatus.EXPANDED,
        result={
            "journal_entries": [
                {
                    "entry_id": "runtime_1",
                    "node_id": "",
                    "phase": "pipeline",
                    "action": "runtime_expand",
                    "reason": "新增子任务",
                    "evidence": child.name,
                    "metadata": {},
                    "created_at": "2026-04-06T10:00:00",
                }
            ]
        },
    )

    monkeypatch.setattr(
        "autospider.graph.subgraphs.multi_dispatch._refresh_plan_artifacts",
        lambda plan, params: (plan, "knowledge"),
    )

    merged = merge_dispatch_round(
        {
            "task_plan": plan,
            "normalized_params": {},
            "dispatch_queue": [pending.model_dump(mode="python")],
            "spawned_subtasks": [child.model_dump(mode="python")],
            "subtask_results": [result_item],
        }
    )

    assert [item["id"] for item in merged["dispatch_queue"]] == [pending.id, child.id]
    assert [subtask.id for subtask in merged["task_plan"].subtasks] == [parent.id, pending.id, child.id]
    assert merged["summary"]["expanded"] == 1
    assert merged["task_plan"].journal[0].action == "runtime_expand"
