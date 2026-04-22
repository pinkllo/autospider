from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autospider.platform.config.runtime import config
from autospider.contexts.planning.domain import ExecutionBrief, SubTask, SubTaskMode, TaskPlan
from autospider.contexts.planning.domain.runtime import SubTaskRuntimeState
from autospider.composition.graph._multi_dispatch import (
    complete_dispatch,
    finalize_subtask_flow,
    initialize_multi_dispatch,
    prepare_dispatch_batch,
)
from autospider.composition.taskplane.scheduler import TaskScheduler
from autospider.composition.taskplane.store.memory_store import MemoryStore
from autospider.composition.taskplane_adapter.graph_integration import (
    close_all_taskplane_sessions,
    ensure_taskplane_plan_registered,
    get_taskplane_scheduler,
    register_taskplane_plan,
)
import autospider.composition.taskplane_adapter.graph_integration as graph_integration_module


def _plan(plan_id: str = "plan-taskplane") -> TaskPlan:
    return TaskPlan(
        plan_id=plan_id,
        original_request="采集公告",
        site_url="https://example.com",
        subtasks=[
            SubTask(
                id="subtask-001",
                name="公告",
                list_url="https://example.com/list",
                task_description="采集公告列表",
                mode=SubTaskMode.COLLECT,
                execution_brief=ExecutionBrief(objective="采集"),
            )
        ],
    )


def _reset_taskplane_sessions() -> None:
    asyncio.run(close_all_taskplane_sessions())


@pytest.fixture(autouse=True)
def _setup_taskplane_runtime(monkeypatch: pytest.MonkeyPatch):
    _reset_taskplane_sessions()
    monkeypatch.setattr(config.taskplane, "enabled", True)
    monkeypatch.setattr(config.taskplane, "store", "memory")
    yield
    _reset_taskplane_sessions()


@pytest.mark.asyncio
async def test_register_taskplane_plan_submits_envelope() -> None:
    plan = _plan("plan-register")

    envelope_id = await register_taskplane_plan(
        thread_id="thread-register",
        plan=plan,
        request_params={"output_dir": "output"},
        source_agent="test",
    )

    scheduler = get_taskplane_scheduler(
        thread_id="thread-register",
        plan_id=plan.plan_id,
    )
    progress = await scheduler.get_envelope_progress(envelope_id)
    assert envelope_id == "plan-register"
    assert progress.total == 1
    assert progress.queued == 1


@pytest.mark.asyncio
async def test_multi_dispatch_nodes_pull_and_report_via_taskplane() -> None:
    plan = _plan("plan-dispatch")
    base_state = {
        "thread_id": "thread-dispatch",
        "normalized_params": {"output_dir": "output"},
        "control": {
            "task_plan": plan,
            "plan_knowledge": "",
            "current_plan": {},
            "stage_status": "ok",
        },
        "execution": {"subtask_results": [], "dispatch_summary": {}},
    }

    initialized = await initialize_multi_dispatch(base_state)
    prepared = await prepare_dispatch_batch({**base_state, **initialized})
    assert len(prepared["current_batch"]) == 1

    runtime_state = SubTaskRuntimeState.model_validate(
        {
            "subtask_id": "subtask-001",
            "status": "completed",
            "outcome_type": "success",
            "summary": {},
        }
    )
    await finalize_subtask_flow(
        {
            "thread_id": "thread-dispatch",
            "task_plan": plan,
            "taskplane_envelope_id": initialized["taskplane_envelope_id"],
            "subtask_result": runtime_state,
            "round_expand_requests": [],
        }
    )

    scheduler = get_taskplane_scheduler(thread_id="thread-dispatch", plan_id=plan.plan_id)
    progress = await scheduler.get_envelope_progress(plan.plan_id)
    assert progress.completed == 1
    assert progress.queued == 0


@pytest.mark.asyncio
async def test_register_taskplane_plan_rejects_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config.taskplane, "enabled", False)
    with pytest.raises(ValueError, match="taskplane_disabled"):
        await register_taskplane_plan(
            thread_id="thread-disabled",
            plan=_plan("plan-disabled"),
            request_params={},
            source_agent="test",
        )


@pytest.mark.asyncio
async def test_ensure_taskplane_plan_registered_reuses_persisted_envelope_after_session_loss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared_store = MemoryStore()
    monkeypatch.setattr(
        graph_integration_module,
        "_build_scheduler",
        lambda: TaskScheduler(store=shared_store),
    )
    plan = _plan("plan-resume")

    envelope_id = await register_taskplane_plan(
        thread_id="thread-resume",
        plan=plan,
        request_params={"output_dir": "output"},
        source_agent="test",
    )
    graph_integration_module._SESSIONS.clear()

    restored_envelope_id = await ensure_taskplane_plan_registered(
        thread_id="thread-resume",
        plan=plan,
        request_params={"output_dir": "output"},
        source_agent="resume",
    )

    restored_scheduler = get_taskplane_scheduler(thread_id="thread-resume", plan_id=plan.plan_id)
    progress = await restored_scheduler.get_envelope_progress(envelope_id)
    assert restored_envelope_id == envelope_id
    assert progress.total == 1
    assert progress.queued == 1
    assert restored_scheduler.is_closed is False


@pytest.mark.asyncio
async def test_same_thread_different_plans_keep_distinct_sessions() -> None:
    plan_a = _plan("plan-thread-a")
    plan_b = _plan("plan-thread-b")

    await register_taskplane_plan(
        thread_id="thread-shared",
        plan=plan_a,
        request_params={"output_dir": "output"},
        source_agent="test-a",
    )
    await register_taskplane_plan(
        thread_id="thread-shared",
        plan=plan_b,
        request_params={"output_dir": "output"},
        source_agent="test-b",
    )

    scheduler_a = get_taskplane_scheduler(thread_id="thread-shared", plan_id=plan_a.plan_id)
    scheduler_b = get_taskplane_scheduler(thread_id="thread-shared", plan_id=plan_b.plan_id)
    progress_a = await scheduler_a.get_envelope_progress(plan_a.plan_id)
    progress_b = await scheduler_b.get_envelope_progress(plan_b.plan_id)

    assert scheduler_a is not scheduler_b
    assert progress_a.total == 1
    assert progress_b.total == 1


@pytest.mark.asyncio
async def test_finalize_subtask_flow_rehydrates_taskplane_session_after_session_loss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared_store = MemoryStore()
    monkeypatch.setattr(
        graph_integration_module,
        "_build_scheduler",
        lambda: TaskScheduler(store=shared_store),
    )
    plan = _plan("plan-resume-finalize")

    await register_taskplane_plan(
        thread_id="thread-resume-finalize",
        plan=plan,
        request_params={"output_dir": "output"},
        source_agent="test",
    )
    graph_integration_module._SESSIONS.clear()

    runtime_state = SubTaskRuntimeState.model_validate(
        {
            "subtask_id": "subtask-001",
            "status": "completed",
            "outcome_type": "success",
            "summary": {},
        }
    )
    await finalize_subtask_flow(
        {
            "thread_id": "thread-resume-finalize",
            "normalized_params": {"output_dir": "output"},
            "task_plan": plan,
            "subtask_result": runtime_state,
            "round_expand_requests": [],
        }
    )

    restored_scheduler = get_taskplane_scheduler(
        thread_id="thread-resume-finalize",
        plan_id=plan.plan_id,
    )
    progress = await restored_scheduler.get_envelope_progress(plan.plan_id)
    assert progress.completed == 1
    assert progress.queued == 0


@pytest.mark.asyncio
async def test_complete_dispatch_closes_taskplane_session() -> None:
    plan = _plan("plan-complete-close")
    base_state = {
        "thread_id": "thread-complete-close",
        "normalized_params": {"output_dir": "output"},
        "control": {
            "task_plan": plan,
            "plan_knowledge": "",
            "current_plan": {},
            "stage_status": "ok",
        },
        "execution": {"subtask_results": [], "dispatch_summary": {}},
    }

    initialized = await initialize_multi_dispatch(base_state)
    scheduler = get_taskplane_scheduler(
        thread_id="thread-complete-close",
        plan_id=plan.plan_id,
    )
    runtime_state = SubTaskRuntimeState.model_validate(
        {
            "subtask_id": "subtask-001",
            "status": "completed",
            "outcome_type": "success",
            "summary": {},
        }
    )

    await finalize_subtask_flow(
        {
            "thread_id": "thread-complete-close",
            "normalized_params": {"output_dir": "output"},
            "task_plan": plan,
            "subtask_result": runtime_state,
            "round_expand_requests": [],
        }
    )
    completed = await complete_dispatch(
        {
            **base_state,
            **initialized,
            "execution": {
                "subtask_results": [runtime_state],
                "dispatch_summary": {},
            },
        }
    )

    assert completed["node_status"] == "ok"
    assert scheduler.is_closed
    with pytest.raises(ValueError, match="taskplane_session_not_found"):
        get_taskplane_scheduler(thread_id="thread-complete-close", plan_id=plan.plan_id)

