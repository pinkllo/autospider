from __future__ import annotations

from types import SimpleNamespace

import pytest

from autospider.contexts.planning.domain import ExecutionBrief, PlanNodeType, TaskPlan
from autospider.contexts.planning.infrastructure.adapters import (
    entry_planning as entry_planning_module,
)
from autospider.contexts.planning.infrastructure.adapters.entry_planning import (
    PlannerEntryPlanner,
)
from autospider.contexts.planning.infrastructure.adapters.task_planner import TaskPlanner


class _FakePage:
    def __init__(self, url: str = "") -> None:
        self.url = url
        self.goto_calls: list[dict[str, object]] = []

    async def goto(
        self,
        url: str,
        wait_until: str = "domcontentloaded",
        timeout: int = 30000,
    ) -> None:
        self.url = url
        self.goto_calls.append(
            {"url": url, "wait_until": wait_until, "timeout": timeout}
        )


class _FakePlanRecords:
    def __init__(self) -> None:
        self.saved_plan: TaskPlan | None = None
        self.written_plan: TaskPlan | None = None
        self.sedimented_plan: TaskPlan | None = None
        self.journal_actions: list[str] = []
        self.collectable_subtask_id = ""

    def build_plan(self, subtasks):
        return TaskPlan(
            plan_id="plan-entry",
            original_request="采集公告",
            site_url="https://example.com/notices",
            subtasks=list(subtasks),
            nodes=[],
            journal=[],
            total_subtasks=len(subtasks),
            created_at="created-at",
            updated_at="updated-at",
        )

    def save_plan(self, plan: TaskPlan) -> TaskPlan:
        self.saved_plan = plan
        return plan

    def write_knowledge_doc(self, plan: TaskPlan) -> None:
        self.written_plan = plan

    def sediment_draft_skill(self, plan: TaskPlan) -> None:
        self.sedimented_plan = plan

    def register_entry_page(self, **kwargs) -> tuple[int, str]:
        del kwargs
        return 0, "node_001"

    def append_journal(self, **kwargs) -> None:
        self.journal_actions.append(str(kwargs["action"]))

    def mark_entry_collectable(self, *, entry_index: int, subtask_id: str) -> None:
        del entry_index
        self.collectable_subtask_id = subtask_id

    def mark_entry_children(self, *, entry_index: int, children_count: int) -> None:
        del entry_index
        del children_count

    def record_planned_subtask_node(self, **kwargs) -> None:
        del kwargs

    def record_planning_dead_end(self, **kwargs) -> None:
        del kwargs


class _FakePlanner:
    def __init__(self) -> None:
        self.page = _FakePage()
        self.site_url = "https://example.com/notices"
        self.user_request = "采集公告"
        self.planner_status = "success"
        self.terminal_reason = ""
        self._plan_records = _FakePlanRecords()
        self.wait_ready_calls = 0
        self._page_state_runtime = self._FakePageStateRuntime(self)

    class _FakePageStateRuntime:
        def __init__(self, planner: "_FakePlanner") -> None:
            self._planner = planner

        async def wait_for_planner_page_ready(self) -> None:
            self._planner.wait_ready_calls += 1

        def build_page_state_signature(
            self,
            current_url: str,
            nav_steps: list[dict] | None,
        ) -> str:
            return f"{current_url}::{len(list(nav_steps or []))}"

    async def _analyze_site_structure(
        self,
        screenshot_base64: str,
        snapshot: object,
        *,
        node_context: dict[str, str] | None = None,
        nav_steps: list[dict] | None = None,
    ) -> dict | None:
        assert screenshot_base64 == "encoded-screenshot"
        assert getattr(snapshot, "marks", []) == []
        assert node_context == {}
        assert nav_steps == []
        return {
            "page_type": "list_page",
            "name": "公告列表",
            "observations": "入口页面已经是列表",
            "task_description": "直接采集公告列表",
        }

    def _resolve_plan_node_type_for_state(
        self,
        page_type: str,
        nav_steps: list[dict] | None,
    ) -> PlanNodeType:
        del nav_steps
        return PlanNodeType.LEAF if page_type == "list_page" else PlanNodeType.CATEGORY

    def _build_collect_task_description(self, context: dict[str, str] | None) -> str:
        del context
        return "fallback-collect"

    def _build_collect_execution_brief(
        self,
        context: dict[str, str] | None,
        *,
        task_description: str,
    ) -> ExecutionBrief:
        del context
        return ExecutionBrief(current_scope="公告列表", objective=task_description)

    async def _extract_subtask_variants(
        self,
        analysis: dict,
        snapshot: object,
        parent_nav_steps: list[dict] | None = None,
        parent_context: dict[str, str] | None = None,
    ) -> list:
        del analysis
        del snapshot
        del parent_nav_steps
        del parent_context
        raise AssertionError("list_page path should not resolve child variants")

    def _build_subtasks_from_variants(
        self,
        variants: list,
        *,
        analysis: dict,
        depth: int,
        mode,
    ) -> list:
        del variants
        del analysis
        del depth
        del mode
        raise AssertionError("list_page path should not build expand subtasks")


@pytest.mark.asyncio
async def test_entry_planner_builds_and_persists_collect_plan(monkeypatch) -> None:
    planner = _FakePlanner()

    async def _fake_inject_and_scan(page) -> object:
        assert page is planner.page
        return SimpleNamespace(marks=[])

    async def _fake_capture_screenshot_with_marks(page) -> tuple[str, str]:
        assert page is planner.page
        return "", "encoded-screenshot"

    async def _fake_clear_overlay(page) -> None:
        assert page is planner.page

    monkeypatch.setattr(entry_planning_module, "inject_and_scan", _fake_inject_and_scan)
    monkeypatch.setattr(
        entry_planning_module,
        "capture_screenshot_with_marks",
        _fake_capture_screenshot_with_marks,
    )
    monkeypatch.setattr(entry_planning_module, "clear_overlay", _fake_clear_overlay)

    result = await PlannerEntryPlanner(planner).plan()

    assert planner.page.goto_calls == [
        {
            "url": "https://example.com/notices",
            "wait_until": "domcontentloaded",
            "timeout": 30000,
        }
    ]
    assert planner.wait_ready_calls == 1
    assert result.subtasks[0].id == "leaf_001"
    assert result.subtasks[0].task_description == "直接采集公告列表"
    assert planner._plan_records.collectable_subtask_id == "leaf_001"
    assert planner._plan_records.journal_actions == [
        "analyze_page",
        "register_leaf_subtask",
    ]
    assert planner._plan_records.saved_plan is result
    assert planner._plan_records.written_plan is result
    assert planner._plan_records.sedimented_plan is result


@pytest.mark.asyncio
async def test_task_planner_plan_delegates_to_entry_planner() -> None:
    expected = object()

    class _StubEntryPlanner:
        async def plan(self):
            return expected

    planner = TaskPlanner.__new__(TaskPlanner)
    planner._entry_planner = _StubEntryPlanner()

    assert await planner.plan() is expected


def test_task_planner_post_process_analysis_delegates_to_processor() -> None:
    expected = {"status": "ok"}
    snapshot = object()
    result = {"page_type": "list_page"}
    node_context = {"category_name": "公告"}

    class _StubPostProcessor:
        def _post_process_analysis(
            self,
            actual_result: dict,
            actual_snapshot: object,
            *,
            node_context: dict[str, str] | None = None,
        ) -> dict:
            assert actual_result is result
            assert actual_snapshot is snapshot
            assert node_context == {"category_name": "公告"}
            return expected

    planner = TaskPlanner.__new__(TaskPlanner)
    planner._analysis_post_processor = _StubPostProcessor()

    assert (
        planner._post_process_analysis(result, snapshot, node_context=node_context) is expected
    )


def test_task_planner_looks_like_current_category_delegates_to_processor() -> None:
    analysis = {"current_selected_category": "公告"}

    class _StubPostProcessor:
        def _looks_like_current_category(self, name: str, actual_analysis: dict) -> bool:
            assert name == "公告"
            assert actual_analysis is analysis
            return True

    planner = TaskPlanner.__new__(TaskPlanner)
    planner._analysis_post_processor = _StubPostProcessor()

    assert planner._looks_like_current_category("公告", analysis) is True
