from __future__ import annotations

from autospider.common.config import config
from autospider.domain.planning import SubTask, TaskPlan
from autospider.graph.subgraphs.multi_dispatch import (
    _inherit_parent_nav_steps,
    _resolve_runtime_replan_max_children,
    _resolve_runtime_subtasks_use_main_model,
    prepare_dispatch_batch,
)


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
        getattr(config.planner, "runtime_subtasks_max_children", 1)
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
