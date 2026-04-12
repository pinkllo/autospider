from __future__ import annotations

import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autospider.crawler.planner.task_planner import (
    build_planner_control_payload,
    build_planner_world_payload,
)
from autospider.domain.planning import (
    ExecutionBrief,
    PlanJournalEntry,
    PlanNode,
    PlanNodeType,
    SubTask,
    SubTaskMode,
    TaskPlan,
)


def _build_task_plan() -> TaskPlan:
    entry_node = PlanNode(
        node_id="node_001",
        name="招标公告",
        node_type=PlanNodeType.CATEGORY,
        url="https://example.com/notices",
        task_description="进入招标公告列表",
        observations="页面展示按公告类型划分的分类入口",
        depth=0,
        context={"channel": "招标公告"},
        children_count=1,
    )
    child_node = PlanNode(
        node_id="node_002",
        parent_node_id="node_001",
        name="采购公告",
        node_type=PlanNodeType.LEAF,
        url="https://example.com/notices/purchase",
        anchor_url="https://example.com/notices",
        page_state_signature="sig-purchase",
        task_description="采集采购公告列表中的详情链接",
        depth=1,
        nav_steps=[{"action": "click", "target_text": "采购公告"}],
        context={"channel": "采购公告"},
        subtask_id="leaf_001",
        is_leaf=True,
        executable=True,
    )
    subtask = SubTask(
        id="leaf_001",
        name="采购公告",
        list_url="https://example.com/notices/purchase",
        anchor_url="https://example.com/notices",
        page_state_signature="sig-purchase",
        task_description="采集采购公告列表中的详情链接",
        depth=1,
        mode=SubTaskMode.COLLECT,
        execution_brief=ExecutionBrief(
            parent_chain=["招标公告"],
            current_scope="采购公告",
            objective="收集采购公告详情页链接",
        ),
        plan_node_id="node_002",
    )
    journal = [
        PlanJournalEntry(
            entry_id="journal_0001",
            node_id="node_001",
            phase="planning",
            action="analyze_page",
            reason="入口页识别为分类页",
            evidence="存在多个公告类型入口",
            metadata={"depth": "0"},
            created_at="2026-04-12T10:00:00",
        ),
        PlanJournalEntry(
            entry_id="journal_0002",
            node_id="node_001",
            phase="planning",
            action="expand_category",
            reason="生成采购公告子任务",
            evidence="采购公告",
            metadata={"children_count": "1"},
            created_at="2026-04-12T10:00:01",
        ),
    ]
    return TaskPlan(
        plan_id="plan_001",
        original_request="采集采购公告详情页",
        site_url="https://example.com",
        subtasks=[subtask],
        nodes=[entry_node, child_node],
        journal=journal,
        total_subtasks=1,
        shared_fields=[
            {"name": "title", "description": "公告标题", "required": True},
            {"name": "published_at", "description": "发布时间", "required": True},
        ],
        created_at="2026-04-12T10:00:00",
        updated_at="2026-04-12T10:00:01",
    )


def test_build_planner_world_payload_seeds_structured_entry_page_model() -> None:
    plan = _build_task_plan()

    payload = build_planner_world_payload(
        plan,
        request_params={
            "list_url": "https://example.com/notices",
            "target_url_count": 12,
        },
    )

    assert payload["failure_records"] == []
    assert payload["world_model"]["request_params"]["target_url_count"] == 12
    page_model = payload["world_model"]["page_models"]["node_001"]
    assert page_model["url"] == "https://example.com/notices"
    assert page_model["page_type"] == "category"
    assert page_model["links"] == 1
    assert page_model["metadata"]["observations"] == "页面展示按公告类型划分的分类入口"
    assert page_model["metadata"]["shared_fields"][0]["name"] == "title"
    assert page_model["metadata"]["journal_summary"][0]["action"] == "analyze_page"


def test_build_planner_control_payload_uses_current_entry_goal_and_dispatch_limits() -> None:
    plan = _build_task_plan()

    payload = build_planner_control_payload(
        plan,
        request_params={
            "max_concurrent": 3,
            "target_url_count": 12,
        },
    )

    assert payload["current_plan"]["page_id"] == "node_001"
    assert payload["current_plan"]["goal"] == "进入招标公告列表"
    assert payload["current_plan"]["metadata"]["entry_url"] == "https://example.com/notices"
    assert payload["dispatch_policy"]["strategy"] == "parallel"
    assert payload["dispatch_policy"]["max_concurrency"] == 3
    assert payload["recovery_policy"]["max_retries"] == 2
