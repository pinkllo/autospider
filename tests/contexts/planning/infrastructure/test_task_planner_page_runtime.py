from __future__ import annotations

import pytest

from autospider.contexts.planning.domain import ExecutionBrief, SubTask
from autospider.contexts.planning.infrastructure.adapters.analysis_support import (
    RuntimeSubtaskPlanResult,
)
from autospider.contexts.planning.infrastructure.adapters.page_runtime import (
    PlannerPageStateRuntime,
)
from autospider.contexts.planning.infrastructure.adapters.task_planner import TaskPlanner


@pytest.mark.asyncio
async def test_task_planner_plan_runtime_subtasks_delegates_to_page_runtime() -> None:
    parent_subtask = SubTask(
        id="sub_001",
        name="公告列表",
        list_url="https://example.com/notices",
        task_description="采集公告",
        execution_brief=ExecutionBrief(current_scope="公告", objective="采集公告"),
    )
    expected = RuntimeSubtaskPlanResult(page_type="list_page", analysis={"page_type": "list_page"})

    class _StubPageRuntime:
        async def plan_runtime_subtasks(
            self,
            *,
            parent_subtask: SubTask,
            max_children: int | None = None,
        ) -> RuntimeSubtaskPlanResult:
            assert parent_subtask.id == "sub_001"
            assert max_children == 5
            return expected

    planner = TaskPlanner.__new__(TaskPlanner)
    planner._page_runtime = _StubPageRuntime()

    assert await planner.plan_runtime_subtasks(parent_subtask=parent_subtask, max_children=5) is expected


@pytest.mark.asyncio
async def test_page_state_runtime_helpers_delegate_to_page_state() -> None:
    restored_original_urls: list[str] = []

    class _StubPageState:
        def build_page_state_signature(self, current_url: str, nav_steps: list[dict] | None) -> str:
            assert current_url == "https://example.com/notices"
            assert nav_steps == [{"action": "click", "target_text": "公告"}]
            return "state::1"

        async def restore_page_state(self, target_url: str, nav_steps: list[dict] | None) -> bool:
            assert target_url == "https://example.com/notices"
            assert nav_steps == [{"action": "click", "target_text": "公告"}]
            return True

        async def enter_child_state(
            self,
            current_url: str,
            child_url: str,
            child_nav_steps: list[dict] | None,
            current_nav_steps: list[dict] | None,
        ) -> bool:
            assert current_url == "https://example.com/notices"
            assert child_url == "https://example.com/notices?tab=notice"
            assert child_nav_steps == [{"action": "click", "target_text": "通知公告"}]
            assert current_nav_steps == [{"action": "click", "target_text": "公告"}]
            return True

        def build_nav_click_step(self, snapshot: object, mark_id: int) -> dict[str, object]:
            assert snapshot is marker
            assert mark_id == 7
            return {"action": "click", "mark_id": 7}

        async def get_dom_signature(self) -> str:
            return "dom::abc"

        async def get_element_interaction_state(self, xpath: str) -> dict[str, str]:
            assert xpath == "//button[@id='notice']"
            return {"aria-selected": "true"}

        def did_interaction_state_activate(self, before: dict | None, after: dict | None) -> bool:
            assert before == {"aria-selected": "false"}
            assert after == {"aria-selected": "true"}
            return True

        async def restore_original_page(self, original_url: str) -> None:
            restored_original_urls.append(original_url)

    marker = object()
    runtime = PlannerPageStateRuntime(page=object(), page_state=_StubPageState())

    assert (
        runtime.build_page_state_signature(
            "https://example.com/notices",
            [{"action": "click", "target_text": "公告"}],
        )
        == "state::1"
    )
    assert await runtime.restore_page_state(
        "https://example.com/notices",
        [{"action": "click", "target_text": "公告"}],
    )
    assert await runtime.enter_child_state(
        "https://example.com/notices",
        "https://example.com/notices?tab=notice",
        [{"action": "click", "target_text": "通知公告"}],
        [{"action": "click", "target_text": "公告"}],
    )
    assert runtime.build_nav_click_step(marker, 7) == {"action": "click", "mark_id": 7}
    assert await runtime.get_dom_signature() == "dom::abc"
    assert await runtime.get_element_interaction_state("//button[@id='notice']") == {
        "aria-selected": "true"
    }
    assert runtime.did_interaction_state_activate(
        {"aria-selected": "false"},
        {"aria-selected": "true"},
    )
    await runtime.restore_original_page("https://example.com/notices")
    assert restored_original_urls == ["https://example.com/notices"]


@pytest.mark.asyncio
async def test_page_state_runtime_wait_for_planner_page_ready_preserves_fallback_wait() -> None:
    calls: list[tuple[str, object]] = []

    class _FakePage:
        async def wait_for_load_state(self, state: str, timeout: int) -> None:
            calls.append(("load_state", {"state": state, "timeout": timeout}))
            raise RuntimeError("networkidle timeout")

        async def wait_for_timeout(self, timeout_ms: int) -> None:
            calls.append(("timeout", timeout_ms))

    runtime = PlannerPageStateRuntime(page=_FakePage(), page_state=object())

    await runtime.wait_for_planner_page_ready()

    assert calls == [
        ("load_state", {"state": "networkidle", "timeout": 5000}),
        ("timeout", 1500),
    ]
