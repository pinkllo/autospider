from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autospider.common.config import config
from autospider.contexts.planning.domain import ExecutionBrief, SubTask, SubTaskMode, TaskPlan
from autospider.domain.runtime import SubTaskRuntimeState
from autospider.graph.subgraphs.multi_dispatch import (
    finalize_subtask_flow,
    initialize_multi_dispatch,
    prepare_dispatch_batch,
)
from autospider.taskplane_adapter.graph_integration import (
    get_taskplane_scheduler,
    register_taskplane_plan,
)
import autospider.taskplane_adapter.graph_integration as graph_integration_module


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


@pytest.fixture(autouse=True)
def _setup_taskplane_runtime(monkeypatch: pytest.MonkeyPatch):
    graph_integration_module._SESSIONS.clear()
    monkeypatch.setattr(config.taskplane, "enabled", True)
    monkeypatch.setattr(config.taskplane, "store", "memory")
    yield
    graph_integration_module._SESSIONS.clear()


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
        "control": {"task_plan": plan, "plan_knowledge": "", "current_plan": {}, "stage_status": "ok"},
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
async def test_register_taskplane_plan_rejects_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config.taskplane, "enabled", False)
    with pytest.raises(ValueError, match="taskplane_disabled"):
        await register_taskplane_plan(
            thread_id="thread-disabled",
            plan=_plan("plan-disabled"),
            request_params={},
            source_agent="test",
        )
