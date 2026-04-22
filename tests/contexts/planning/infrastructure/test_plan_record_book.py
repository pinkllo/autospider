from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from autospider.contexts.planning.domain import PlanNodeType, SubTask, SubTaskMode
from autospider.contexts.planning.infrastructure.adapters.plan_records import (
    PlannerPlanRecordBook,
)
from autospider.contexts.planning.infrastructure.repositories.artifact_store import (
    ArtifactPlanRepository,
)


def _build_record_book(tmp_path: Path) -> PlannerPlanRecordBook:
    repository = ArtifactPlanRepository(
        site_url="https://example.com/notices",
        user_request="采集公告",
        output_dir=str(tmp_path / "planner-record-book"),
    )
    return PlannerPlanRecordBook(artifacts=repository)


def test_plan_record_book_registers_entry_node() -> None:
    record_book = _build_record_book(Path("artifacts/test_tmp") / uuid4().hex)
    entry_index, node_id = record_book.register_entry_page(
        current_url="https://example.com/notices",
        page_type="list_page",
        node_name="公告列表",
        observations="入口页已经是列表",
        task_description="直接采集公告列表",
        page_state_signature="sig-entry",
        node_type=PlanNodeType.LEAF,
    )
    record_book.append_journal(
        node_id=node_id,
        phase="planning",
        action="analyze_page",
        reason="入口识别为列表页",
        evidence="无需继续拆分",
    )
    subtask = SubTask(
        id="leaf_001",
        name="公告列表",
        list_url="https://example.com/notices",
        anchor_url="https://example.com/notices",
        page_state_signature="sig-entry",
        task_description="直接采集公告列表",
        mode=SubTaskMode.COLLECT,
    )
    record_book.mark_entry_collectable(entry_index=entry_index, subtask_id=subtask.id)

    plan = record_book.build_plan([subtask])

    assert len(plan.nodes) == 1
    assert plan.nodes[0].node_id == node_id
    assert plan.nodes[0].is_leaf is True
    assert plan.nodes[0].executable is True
    assert plan.nodes[0].subtask_id == "leaf_001"
    assert plan.journal[0].action == "analyze_page"


def test_plan_record_book_records_stateful_child_node() -> None:
    record_book = _build_record_book(Path("artifacts/test_tmp") / uuid4().hex)
    _, parent_node_id = record_book.register_entry_page(
        current_url="https://example.com/notices",
        page_type="category",
        node_name="公告分类",
        observations="入口页有分类切换",
        task_description="进入公告分类",
        page_state_signature="sig-root",
        node_type=PlanNodeType.CATEGORY,
    )
    child_subtask = SubTask(
        id="leaf_purchase",
        name="采购公告",
        list_url="https://example.com/notices",
        anchor_url="https://example.com/notices",
        page_state_signature="sig-purchase",
        task_description="采集采购公告",
        nav_steps=[{"action": "click", "target_text": "采购公告"}],
        context={"category_name": "采购公告"},
        depth=1,
        mode=SubTaskMode.COLLECT,
    )

    record_book.record_planned_subtask_node(
        subtask=child_subtask,
        parent_node_id=parent_node_id,
        reason="入口页生成子任务",
    )
    plan = record_book.build_plan([child_subtask])

    assert len(plan.nodes) == 2
    assert plan.nodes[1].parent_node_id == parent_node_id
    assert plan.nodes[1].node_type == PlanNodeType.STATEFUL_LIST
    assert plan.nodes[1].subtask_id == "leaf_purchase"
    assert plan.journal[0].action == "create_subtask"


def test_plan_record_book_marks_dead_end_as_non_executable() -> None:
    record_book = _build_record_book(Path("artifacts/test_tmp") / uuid4().hex)
    entry_index, node_id = record_book.register_entry_page(
        current_url="https://example.com/notices",
        page_type="category",
        node_name="公告分类",
        observations="入口页有分类切换",
        task_description="进入公告分类",
        page_state_signature="sig-root",
        node_type=PlanNodeType.CATEGORY,
    )

    record_book.record_planning_dead_end(
        entry_index=entry_index,
        node_id=node_id,
        reason="未识别出子分类",
        evidence="页面仅剩筛选项",
        metadata={"depth": "0"},
    )
    plan = record_book.build_plan([])

    assert len(plan.nodes) == 1
    assert plan.nodes[0].is_leaf is False
    assert plan.nodes[0].executable is False
    assert plan.nodes[0].children_count == 0
    assert plan.journal[0].action == "planning_dead_end"
