from __future__ import annotations

import pytest

from autospider.contexts.planning.infrastructure.adapters.task_planner import TaskPlanner


def test_task_planner_build_planner_candidates_delegates_to_variant_resolver() -> None:
    snapshot = object()

    class _StubVariantResolver:
        def _build_planner_candidates(
            self,
            actual_snapshot: object,
            max_candidates: int = 30,
        ) -> str:
            assert actual_snapshot is snapshot
            assert max_candidates == 12
            return "- [1] 公告"

    planner = TaskPlanner.__new__(TaskPlanner)
    planner._variant_resolver = _StubVariantResolver()

    assert planner._build_planner_candidates(snapshot, max_candidates=12) == "- [1] 公告"


@pytest.mark.asyncio
async def test_task_planner_extract_subtask_variants_delegates_to_variant_resolver() -> None:
    analysis = {"subtasks": [{"name": "交通运输工程"}]}
    snapshot = object()
    parent_nav_steps = [{"action": "click", "target_text": "工学"}]
    parent_context = {"category_name": "工学"}
    expected = [object()]

    class _StubVariantResolver:
        async def _extract_subtask_variants(
            self,
            actual_analysis: dict,
            actual_snapshot: object,
            parent_nav_steps: list[dict] | None = None,
            parent_context: dict[str, str] | None = None,
        ) -> list[object]:
            assert actual_analysis is analysis
            assert actual_snapshot is snapshot
            assert parent_nav_steps == [{"action": "click", "target_text": "工学"}]
            assert parent_context == {"category_name": "工学"}
            return expected

    planner = TaskPlanner.__new__(TaskPlanner)
    planner._variant_resolver = _StubVariantResolver()

    assert (
        await planner._extract_subtask_variants(
            analysis,
            snapshot,
            parent_nav_steps=parent_nav_steps,
            parent_context=parent_context,
        )
        is expected
    )
