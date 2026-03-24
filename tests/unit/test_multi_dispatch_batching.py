from __future__ import annotations

from autospider.common.config import config
from autospider.graph.subgraphs.multi_dispatch import (
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
    assert _resolve_runtime_replan_max_children({}) == config.planner.runtime_subtasks_max_children
    assert _resolve_runtime_subtasks_use_main_model({}) is bool(
        config.planner.runtime_subtasks_use_main_model
    )


def test_runtime_replan_limits_accept_overrides():
    assert _resolve_runtime_replan_max_children({"runtime_subtask_max_children": "3"}) == 3
    assert _resolve_runtime_subtasks_use_main_model({"runtime_subtasks_use_main_model": "false"}) is False
