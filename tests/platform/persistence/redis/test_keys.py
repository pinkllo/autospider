from __future__ import annotations

from autospider.platform.persistence.redis.keys import (
    checkpoint_key,
    events_stream_key,
    lock_key,
    plan_key,
    plan_subtasks_key,
    run_fields_key,
    run_key,
    run_pages_key,
    skill_index_by_host_key,
    skill_key,
    subtask_dead_queue_key,
    subtask_queue_key,
)


def test_key_registry_matches_contract_paths() -> None:
    assert plan_key("plan-1") == "autospider:v1:plan:plan-1"
    assert plan_subtasks_key("plan-1") == "autospider:v1:plan:plan-1:subtasks"
    assert run_key("run-1") == "autospider:v1:run:run-1"
    assert run_pages_key("run-1") == "autospider:v1:run:run-1:pages"
    assert run_fields_key("run-1", "subtask-1") == "autospider:v1:run:run-1:fields:subtask-1"
    assert skill_key("skill-1") == "autospider:v1:skill:skill-1"
    assert skill_index_by_host_key("example.com") == "autospider:v1:skill:index:by_host:example.com"
    assert checkpoint_key("thread-1") == "autospider:v1:ckpt:thread-1"
    assert events_stream_key("planning") == "autospider:v1:stream:events.planning"
    assert subtask_queue_key() == "autospider:v1:stream:queue.subtask"
    assert subtask_dead_queue_key() == "autospider:v1:stream:queue.subtask.dead"
    assert lock_key("plan:1") == "autospider:v1:lock:plan:1"
