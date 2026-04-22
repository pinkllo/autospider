from __future__ import annotations

from autospider.contexts.planning.domain import ExecutionBrief, PlanNodeType, SubTaskMode
from autospider.contexts.planning.infrastructure.adapters.task_planner import TaskPlanner


def test_task_planner_resolve_plan_node_type_delegates_to_subtask_builder() -> None:
    nav_steps = [{"action": "click", "target_text": "交通运输工程"}]

    class _StubSubtaskBuilder:
        def _resolve_plan_node_type_for_state(
            self,
            page_type: str,
            actual_nav_steps: list[dict] | None,
        ) -> PlanNodeType:
            assert page_type == "list_page"
            assert actual_nav_steps == nav_steps
            return PlanNodeType.STATEFUL_LIST

    planner = TaskPlanner.__new__(TaskPlanner)
    planner._subtask_builder = _StubSubtaskBuilder()

    assert (
        planner._resolve_plan_node_type_for_state("list_page", nav_steps)
        is PlanNodeType.STATEFUL_LIST
    )


def test_task_planner_build_subtasks_delegates_to_subtask_builder() -> None:
    variants = [object()]
    analysis = {"subtasks": [{"name": "交通运输工程"}]}
    parent_brief = ExecutionBrief(current_scope="工学", objective="继续下钻")
    expected = [object()]

    class _StubSubtaskBuilder:
        def _build_subtasks_from_variants(
            self,
            actual_variants: list,
            *,
            analysis: dict,
            depth: int,
            mode: SubTaskMode,
            parent_id: str | None = None,
            parent_execution_brief: ExecutionBrief | None = None,
        ) -> list[object]:
            assert actual_variants is variants
            assert analysis == {"subtasks": [{"name": "交通运输工程"}]}
            assert depth == 1
            assert mode is SubTaskMode.EXPAND
            assert parent_id == "parent_001"
            assert parent_execution_brief is parent_brief
            return expected

    planner = TaskPlanner.__new__(TaskPlanner)
    planner._subtask_builder = _StubSubtaskBuilder()

    assert (
        planner._build_subtasks_from_variants(
            variants,
            analysis=analysis,
            depth=1,
            mode=SubTaskMode.EXPAND,
            parent_id="parent_001",
            parent_execution_brief=parent_brief,
        )
        is expected
    )


def test_task_planner_collect_helpers_delegate_to_subtask_builder() -> None:
    context = {"category_name": "交通运输工程"}
    parent_brief = ExecutionBrief(current_scope="工学", objective="保持分类作用域")
    expected_brief = ExecutionBrief(current_scope="交通运输工程", objective="采集当前分类")

    class _StubSubtaskBuilder:
        def _build_collect_task_description(
            self,
            actual_context: dict[str, str] | None,
        ) -> str:
            assert actual_context == context
            return "采集当前分类"

        def _build_collect_execution_brief(
            self,
            actual_context: dict[str, str] | None,
            *,
            task_description: str,
            parent_execution_brief: ExecutionBrief | None = None,
        ) -> ExecutionBrief:
            assert actual_context == context
            assert task_description == "采集当前分类"
            assert parent_execution_brief is parent_brief
            return expected_brief

    planner = TaskPlanner.__new__(TaskPlanner)
    planner._subtask_builder = _StubSubtaskBuilder()

    assert planner._build_collect_task_description(context) == "采集当前分类"
    assert (
        planner._build_collect_execution_brief(
            context,
            task_description="采集当前分类",
            parent_execution_brief=parent_brief,
        )
        is expected_brief
    )
