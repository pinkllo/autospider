"""Ensure dispatch/complete phases do not silently drop ``active_strategy``.

Covers the regression where `merge_dispatch_round` / `complete_dispatch`
rebuilt the ``control`` dict from scratch, wiping the replan counter and
breaking the feedback budget.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import pytest

from autospider.contexts.planning.domain import TaskPlan
from autospider.legacy.graph.subgraphs.multi_dispatch import (
    complete_dispatch,
    merge_dispatch_round,
)


@dataclass
class _FakeProgress:
    queued: int = 0
    dispatched: int = 0
    running: int = 0


class _FakeScheduler:
    def __init__(self, progress: _FakeProgress) -> None:
        self._progress = progress

    async def get_envelope_progress(self, envelope_id: str) -> _FakeProgress:
        return self._progress


class _FakePlanMutation:
    def __init__(self, plan: TaskPlan) -> None:
        self.task_plan = plan
        self.plan_knowledge = ""


class _FakePlanMutationService:
    def __init__(self, plan: TaskPlan) -> None:
        self._plan = plan

    def merge_expand_requests(self, **_ignored):  # noqa: ANN001
        return _FakePlanMutation(self._plan)


def _install_fakes(
    monkeypatch: pytest.MonkeyPatch, plan: TaskPlan, progress: _FakeProgress
) -> None:
    import autospider.legacy.graph.subgraphs.multi_dispatch as md

    monkeypatch.setattr(md, "_taskplane_scheduler", lambda state, plan: _FakeScheduler(progress))
    monkeypatch.setattr(md, "_taskplane_envelope_id", lambda state, plan: "env-1")
    monkeypatch.setattr(md, "PlanMutationService", lambda: _FakePlanMutationService(plan))


def _base_state(plan: TaskPlan) -> dict:
    return {
        "thread_id": "thread-001",
        "normalized_params": {"output_dir": "output"},
        "task_plan": plan,
        "control": {
            "task_plan": plan,
            "current_plan": {"goal": "demo"},
            "active_strategy": {"name": "replan", "replan_count": 2, "max_replans": 3},
        },
        "round_subtask_results": [],
        "round_expand_requests": [],
        "execution": {"subtask_results": []},
        "taskplane_envelope_id": "env-1",
    }


def test_merge_dispatch_round_preserves_active_strategy(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = TaskPlan(plan_id="plan-1", site_url="https://example.com", original_request="demo")
    _install_fakes(monkeypatch, plan, _FakeProgress())

    result = asyncio.run(merge_dispatch_round(_base_state(plan)))

    active = result["control"]["active_strategy"]
    assert active["name"] == "replan"
    assert active["replan_count"] == 2
    assert active["max_replans"] == 3


def test_complete_dispatch_preserves_active_strategy(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = TaskPlan(plan_id="plan-2", site_url="https://example.com", original_request="demo")
    _install_fakes(monkeypatch, plan, _FakeProgress())

    result = asyncio.run(complete_dispatch(_base_state(plan)))

    active = result["control"]["active_strategy"]
    assert active["name"] == "replan"
    assert active["replan_count"] == 2
    assert active["max_replans"] == 3
