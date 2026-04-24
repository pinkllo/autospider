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

from types import SimpleNamespace

from autospider.contexts.planning.domain.page_state import PlannerPageState
from autospider.contexts.planning.domain.subtask_builder import PlannerSubtaskBuilder


def test_planner_page_state_build_dedup_signature_ignores_tracking_query_and_normalizes_context() -> None:
    page_state = PlannerPageState(page=object())

    first = page_state.build_dedup_signature(
        current_url="https://example.com/notices/?utm_source=wx&tab=notice&id=1",
        context={"category_path": "公告 > 通知公告", "category_name": "通知公告"},
        variant_label="通知公告",
    )
    second = page_state.build_dedup_signature(
        current_url="https://example.com/notices?tab=notice&id=1&utm_medium=social",
        context={"category_path": ["公告", "通知公告"], "category_name": " 通知公告 "},
        variant_label=" 通知公告 ",
    )

    assert first == second


def test_subtask_builder_dedupes_variants_by_semantic_identity_instead_of_page_state_signature() -> None:
    class _PlannerStub:
        user_request = "采集通知公告"

        def _format_context_path(self, context: dict[str, str] | None) -> str:
            path = (context or {}).get("category_path") or ""
            return str(path).replace("|", " > ")

        def _sanitize_context(self, context: dict[str, str] | None) -> dict[str, str]:
            return dict(context or {})

        def _extract_category_path(self, context: dict[str, str] | None) -> list[str]:
            raw = str((context or {}).get("category_path") or "")
            return [item.strip() for item in raw.split(">") if item.strip()]

        def _normalize_semantic_label(self, value: str) -> str:
            return " ".join(str(value or "").strip().lower().split())

        def _build_dedup_signature(
            self,
            *,
            current_url: str,
            context: dict[str, str] | None = None,
            variant_label: str = "",
        ) -> str:
            return PlannerPageState(page=object()).build_dedup_signature(
                current_url=current_url,
                context=context,
                variant_label=variant_label,
            )

        def _resolve_grouped_target_count(self):
            return None

    builder = PlannerSubtaskBuilder(_PlannerStub())
    variants = [
        SimpleNamespace(
            page_state_signature="state-a",
            resolved_url="https://example.com/notices?tab=notice&utm_source=wx",
            anchor_url="https://example.com/notices",
            variant_label="通知公告",
            nav_steps=[{"action": "click", "target_text": "通知公告"}],
            context={"category_path": "公告 > 通知公告", "category_name": "通知公告"},
        ),
        SimpleNamespace(
            page_state_signature="state-b",
            resolved_url="https://example.com/notices/?tab=notice",
            anchor_url="https://example.com/notices",
            variant_label=" 通知公告 ",
            nav_steps=[{"action": "click", "target_text": "通知公告"}, {"action": "wait"}],
            context={"category_path": "公告 > 通知公告", "category_name": "通知公告"},
        ),
    ]
    analysis = {"subtasks": [{"name": "通知公告"}, {"name": "通知公告-重复"}]}

    subtasks = builder._build_subtasks_from_variants(
        variants,
        analysis=analysis,
        depth=0,
    )

    assert len(subtasks) == 1
    assert subtasks[0].page_state_signature == "state-a"
    assert subtasks[0].variant_label == "通知公告"
