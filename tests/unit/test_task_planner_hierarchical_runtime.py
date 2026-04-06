from __future__ import annotations

import asyncio
from types import SimpleNamespace

from autospider.crawler.planner.task_planner import ResolvedPlannerVariant, TaskPlanner
from autospider.crawler.planner.planner_state import PlannerPageState
from autospider.domain.planning import ExecutionBrief, SubTask, SubTaskMode


async def _fake_inject_and_scan(page):
    return SimpleNamespace(marks=[])


async def _fake_capture(page):
    return None, "base64"


async def _fake_clear(page):
    return None


def _build_runtime_planner() -> TaskPlanner:
    planner = TaskPlanner.__new__(TaskPlanner)
    planner.page = SimpleNamespace(url="https://example.com/list")
    planner.site_url = "https://example.com/list"
    planner.user_request = "采集工程建设与土地矿业下各个相关分类的项目名称，每类10条"
    planner._knowledge_entries = []
    planner._journal_entries = []
    planner._sibling_category_registry = {}
    planner._page_state = PlannerPageState(SimpleNamespace())
    return planner


def test_plan_entry_subtasks_generates_only_first_level_expand_tasks(monkeypatch):
    planner = _build_runtime_planner()

    async def _fake_analysis(*args, **kwargs):
        return {
            "page_type": "category",
            "name": "交易公开列表",
            "task_description": "拆分一级分类任务",
            "observations": "页面存在工程建设与土地矿业两个一级分类。",
            "subtasks": [
                {"name": "工程建设", "task_description": "继续拆分工程建设"},
                {"name": "土地矿业", "task_description": "继续拆分土地矿业"},
            ],
        }

    async def _fake_extract_variants(*args, **kwargs):
        return [
            ResolvedPlannerVariant(
                resolved_url="https://example.com/list",
                anchor_url="https://example.com/list",
                nav_steps=[{"action": "click", "target_text": "工程建设"}],
                page_state_signature="state_engineering",
                variant_label="工程建设",
                context={"category_name": "工程建设", "category_path": "工程建设"},
            ),
            ResolvedPlannerVariant(
                resolved_url="https://example.com/list",
                anchor_url="https://example.com/list",
                nav_steps=[{"action": "click", "target_text": "土地矿业"}],
                page_state_signature="state_mining",
                variant_label="土地矿业",
                context={"category_name": "土地矿业", "category_path": "土地矿业"},
            ),
        ]

    monkeypatch.setattr("autospider.crawler.planner.task_planner.inject_and_scan", _fake_inject_and_scan)
    monkeypatch.setattr("autospider.crawler.planner.task_planner.capture_screenshot_with_marks", _fake_capture)
    monkeypatch.setattr("autospider.crawler.planner.task_planner.clear_overlay", _fake_clear)
    planner._analyze_site_structure = _fake_analysis
    planner._extract_subtask_variants = _fake_extract_variants

    subtasks = asyncio.run(planner._plan_entry_subtasks())

    assert [subtask.name for subtask in subtasks] == ["工程建设", "土地矿业"]
    assert all(subtask.mode == SubTaskMode.EXPAND for subtask in subtasks)
    assert all(subtask.depth == 1 for subtask in subtasks)
    assert subtasks[0].execution_brief.parent_chain == []
    assert subtasks[0].execution_brief.current_scope == "工程建设"
    assert "先判断当前页面是否仍存在" in subtasks[0].execution_brief.next_action
    assert "不要把同层兄弟分类切换误判为继续下钻" in subtasks[0].execution_brief.do_not
    assert planner._knowledge_entries[0]["children_count"] == 2
    assert planner._journal_entries[-1]["action"] == "create_subtask"


def test_plan_runtime_subtasks_spawns_next_level_expand_children(monkeypatch):
    planner = _build_runtime_planner()

    async def _fake_restore(*args, **kwargs):
        return True

    async def _fake_analysis(*args, **kwargs):
        return {
            "page_type": "category",
            "name": "工程建设",
            "task_description": "继续拆分工程建设",
            "observations": "页面存在房屋建筑和市政基础设施工程、交通运输工程、水利工程、其他工程。",
            "subtasks": [
                {"name": "房屋建筑和市政基础设施工程"},
                {"name": "交通运输工程"},
                {"name": "水利工程"},
                {"name": "其他工程"},
            ],
        }

    async def _fake_extract_variants(*args, **kwargs):
        return [
            ResolvedPlannerVariant(
                resolved_url="https://example.com/list",
                anchor_url="https://example.com/list",
                nav_steps=[{"action": "click", "target_text": name}],
                page_state_signature=f"state_{idx}",
                variant_label=name,
                context={"category_name": name, "category_path": f"工程建设 > {name}"},
            )
            for idx, name in enumerate(
                ["房屋建筑和市政基础设施工程", "交通运输工程", "水利工程", "其他工程"],
                start=1,
            )
        ]

    monkeypatch.setattr("autospider.crawler.planner.task_planner.inject_and_scan", _fake_inject_and_scan)
    monkeypatch.setattr("autospider.crawler.planner.task_planner.capture_screenshot_with_marks", _fake_capture)
    monkeypatch.setattr("autospider.crawler.planner.task_planner.clear_overlay", _fake_clear)
    planner._restore_page_state = _fake_restore
    planner._analyze_site_structure = _fake_analysis
    planner._extract_subtask_variants = _fake_extract_variants

    parent = SubTask(
        id="expand_root",
        name="工程建设",
        list_url="https://example.com/list",
        anchor_url="https://example.com/list",
        page_state_signature="state_parent",
        task_description="爬取工程建设下各个相关分类的项目各10条。",
        context={"category_name": "工程建设", "category_path": "工程建设"},
        nav_steps=[{"action": "click", "target_text": "工程建设"}],
        mode=SubTaskMode.EXPAND,
        execution_brief=ExecutionBrief(current_scope="工程建设"),
    )

    result = asyncio.run(planner.plan_runtime_subtasks(parent_subtask=parent, max_children=0))

    assert len(result.children) == 4
    assert all(child.mode == SubTaskMode.EXPAND for child in result.children)
    assert all(child.parent_id == parent.id for child in result.children)
    assert result.children[0].execution_brief.parent_chain == ["工程建设"]
    assert result.children[0].execution_brief.current_scope == "房屋建筑和市政基础设施工程"
    assert "停止拆分并开始采集当前分类" in result.children[0].execution_brief.stop_rule


def test_plan_runtime_subtasks_falls_back_to_collect_when_no_deeper_category(monkeypatch):
    planner = _build_runtime_planner()

    async def _fake_restore(*args, **kwargs):
        return True

    async def _fake_analysis(*args, **kwargs):
        return {
            "page_type": "category",
            "name": "房屋建筑和市政基础设施工程",
            "task_description": "采集当前房屋建筑和市政基础设施工程分类数据",
            "observations": "当前页面只剩兄弟切换和祖先回跳入口。",
            "subtasks": [],
        }

    async def _fake_extract_variants(*args, **kwargs):
        return []

    monkeypatch.setattr("autospider.crawler.planner.task_planner.inject_and_scan", _fake_inject_and_scan)
    monkeypatch.setattr("autospider.crawler.planner.task_planner.capture_screenshot_with_marks", _fake_capture)
    monkeypatch.setattr("autospider.crawler.planner.task_planner.clear_overlay", _fake_clear)
    planner._restore_page_state = _fake_restore
    planner._analyze_site_structure = _fake_analysis
    planner._extract_subtask_variants = _fake_extract_variants

    parent = SubTask(
        id="expand_leaf",
        name="房屋建筑和市政基础设施工程",
        list_url="https://example.com/list",
        anchor_url="https://example.com/list",
        page_state_signature="state_leaf",
        task_description="爬取房屋建筑和市政基础设施工程下各个相关分类的项目各10条。",
        context={
            "category_name": "房屋建筑和市政基础设施工程",
            "category_path": "工程建设 > 房屋建筑和市政基础设施工程",
        },
        nav_steps=[
            {"action": "click", "target_text": "工程建设"},
            {"action": "click", "target_text": "房屋建筑和市政基础设施工程"},
        ],
        mode=SubTaskMode.EXPAND,
        execution_brief=ExecutionBrief(
            parent_chain=["工程建设"],
            current_scope="房屋建筑和市政基础设施工程",
        ),
    )

    result = asyncio.run(planner.plan_runtime_subtasks(parent_subtask=parent, max_children=0))

    assert result.page_type == "list_page"
    assert result.children == []
    assert result.collect_execution_brief.parent_chain == ["工程建设"]
    assert result.collect_execution_brief.current_scope == "房屋建筑和市政基础设施工程"
    assert "直接在当前页面收集详情链接并翻页" in result.collect_execution_brief.next_action
