from __future__ import annotations

import asyncio
from types import SimpleNamespace

from autospider.crawler.collector import navigation_handler as navigation_handler_module
from autospider.crawler.planner.task_planner import TaskPlanner
from autospider.crawler.planner.planner_state import PlannerPageState


def test_page_state_signature_distinguishes_same_url_different_nav_steps():
    planner = TaskPlanner.__new__(TaskPlanner)
    planner._page_state = PlannerPageState(SimpleNamespace())

    sig_a = planner._build_page_state_signature(
        "https://example.com/list",
        [{"action": "click", "target_text": "招标公告", "thinking": "first"}],
    )
    sig_b = planner._build_page_state_signature(
        "https://example.com/list",
        [{"action": "click", "target_text": "中标公告", "thinking": "second"}],
    )

    assert sig_a != sig_b


def test_page_state_signature_ignores_unstable_nav_fields():
    planner = TaskPlanner.__new__(TaskPlanner)
    planner._page_state = PlannerPageState(SimpleNamespace())

    sig_a = planner._build_page_state_signature(
        "https://example.com/list",
        [{"action": "click", "target_text": "公告", "thinking": "alpha", "success": True}],
    )
    sig_b = planner._build_page_state_signature(
        "https://example.com/list",
        [{"action": "click", "target_text": "公告", "thinking": "beta", "success": False}],
    )

    assert sig_a == sig_b


def test_replay_nav_steps_preserve_success_semantics():
    planner = TaskPlanner.__new__(TaskPlanner)
    planner._page_state = PlannerPageState(SimpleNamespace())

    replay_steps = planner._page_state.normalize_replay_nav_steps(
        [
            {"action": "click", "target_text": "公告"},
            {"action": "click", "target_text": "结果", "success": False},
        ]
    )

    assert replay_steps[0]["success"] is True
    assert replay_steps[1]["success"] is False


def test_enter_child_state_replays_only_incremental_steps_on_same_url(monkeypatch):
    calls: dict[str, object] = {"replayed_steps": None}

    class _FakeNavigationHandler:
        def __init__(self, page, list_url, task_description, max_nav_steps):
            self.page = page

        async def replay_nav_steps(self, nav_steps):
            calls["replayed_steps"] = list(nav_steps)
            return True

    class _FakePage:
        def __init__(self):
            self.goto_calls: list[str] = []
            self.wait_calls = 0

        async def goto(self, url, wait_until=None, timeout=None):
            self.goto_calls.append(url)

        async def wait_for_timeout(self, timeout):
            self.wait_calls += 1

    monkeypatch.setattr(navigation_handler_module, "NavigationHandler", _FakeNavigationHandler)
    page = _FakePage()
    state = PlannerPageState(page)

    result = asyncio.run(
        state.enter_child_state(
            "https://example.com/list",
            "https://example.com/list",
            [
                {"action": "click", "target_text": "工程建设"},
                {"action": "click", "target_text": "招标公告及资格预审"},
            ],
            [{"action": "click", "target_text": "工程建设"}],
        )
    )

    assert result is True
    assert page.goto_calls == []
    assert calls["replayed_steps"] == [{"action": "click", "target_text": "招标公告及资格预审", "text": "", "key": "", "url": "", "scroll_delta": None, "success": True}]


def test_build_subtask_context_inherits_category_path():
    planner = TaskPlanner.__new__(TaskPlanner)

    context = planner._build_subtask_context(
        "招标公告及资格预审",
        parent_context={"category_name": "工程建设", "category_path": "工程建设"},
    )

    assert context["category_name"] == "招标公告及资格预审"
    assert context["category_path"] == "工程建设 > 招标公告及资格预审"


def test_extract_category_path_expands_grouped_labels():
    planner = TaskPlanner.__new__(TaskPlanner)

    path = planner._extract_category_path(
        {"category_path": "工程建设-房屋建筑和市政基础设施工程"}
    )

    assert path == ["工程建设", "房屋建筑和市政基础设施工程"]


def test_same_page_category_cycle_requires_exact_ancestor_match():
    planner = TaskPlanner.__new__(TaskPlanner)

    current_context = {
        "category_name": "招标公告及资格预审",
        "category_path": "土地矿业 > 工程建设分类采集 > 招标公告及资格预审",
    }
    child_context = {
        "category_name": "土地矿业分类采集",
        "category_path": "土地矿业 > 工程建设分类采集 > 招标公告及资格预审 > 土地矿业分类采集",
    }

    result = planner._is_same_page_category_cycle(
        "https://example.com/list",
        "https://example.com/list",
        current_context,
        child_context,
    )

    assert result is False


def test_same_page_category_cycle_detects_exact_revisit_to_ancestor_category():
    planner = TaskPlanner.__new__(TaskPlanner)

    current_context = {
        "category_name": "招标公告及资格预审",
        "category_path": "土地矿业 > 工程建设 > 招标公告及资格预审",
    }
    child_context = {
        "category_name": "土地矿业",
        "category_path": "土地矿业 > 工程建设 > 招标公告及资格预审 > 土地矿业",
    }

    result = planner._is_same_page_category_cycle(
        "https://example.com/list",
        "https://example.com/list",
        current_context,
        child_context,
    )

    assert result is True


def test_semantic_state_signature_uses_exact_category_path_labels():
    planner = TaskPlanner.__new__(TaskPlanner)

    sig_a = planner._build_semantic_state_signature(
        "https://example.com/list",
        {"category_path": "工程建设 > 招标公告及资格预审"},
    )
    sig_b = planner._build_semantic_state_signature(
        "https://example.com/list",
        {"category_path": "工程建设分类采集 > 招标公告及资格预审"},
    )

    assert sig_a != sig_b


def test_post_process_analysis_upgrades_multicategory_request_to_category():
    planner = TaskPlanner.__new__(TaskPlanner)
    planner.user_request = "采集网站中工程建设与土地矿业下各个相关分类的项目名称，每类10条"

    snapshot = SimpleNamespace(
        marks=[
            SimpleNamespace(mark_id=1, tag="a", role="link", text="工程建设", aria_label=None),
            SimpleNamespace(mark_id=2, tag="a", role="link", text="土地矿业", aria_label=None),
            SimpleNamespace(mark_id=3, tag="a", role="link", text="搜索", aria_label=None),
        ]
    )

    result = planner._post_process_analysis(
        {
            "page_type": "list_page",
            "name": "交易公开列表",
            "task_description": "采集列表项目",
            "observations": "页面同时存在分类入口和列表。",
            "subtasks": [],
        },
        snapshot,
    )

    assert result["page_type"] == "category"
    assert [item["name"] for item in result["subtasks"]] == ["工程建设", "土地矿业"]


def test_post_process_analysis_does_not_reupgrade_nested_multicategory_page():
    planner = TaskPlanner.__new__(TaskPlanner)
    planner.user_request = "采集网站中工程建设下各个相关分类的项目名称，每类10条"

    snapshot = SimpleNamespace(
        marks=[
            SimpleNamespace(mark_id=1, tag="a", role="link", text="工程建设", aria_label=None),
            SimpleNamespace(mark_id=2, tag="a", role="link", text="房屋建筑和市政基础设施工程", aria_label=None),
            SimpleNamespace(mark_id=3, tag="a", role="link", text="交通运输工程", aria_label=None),
            SimpleNamespace(mark_id=4, tag="a", role="link", text="水利工程", aria_label=None),
        ]
    )

    result = planner._post_process_analysis(
        {
            "page_type": "list_page",
            "name": "房屋建筑和市政基础设施工程列表",
            "task_description": "采集列表项目",
            "observations": "当前已进入房屋建筑和市政基础设施工程。",
            "subtasks": [],
        },
        snapshot,
        node_context={"category_path": "工程建设 > 房屋建筑和市政基础设施工程"},
    )

    assert result["page_type"] == "list_page"
    assert result["subtasks"] == []


def test_post_process_analysis_collapses_registered_sibling_switches_without_group_prefix():
    planner = TaskPlanner.__new__(TaskPlanner)
    planner.user_request = "采集网站中工程建设下各个相关分类的项目名称，每类10条"
    planner._sibling_category_registry = {
        "工程建设": {
            "房屋建筑和市政基础设施工程",
            "交通运输工程",
            "水利工程",
            "其他工程",
        }
    }

    result = planner._post_process_analysis(
        {
            "page_type": "category",
            "name": "房屋建筑和市政基础设施工程列表",
            "task_description": "继续拆分分类",
            "observations": "当前已进入房屋建筑和市政基础设施工程。",
            "subtasks": [
                {"name": "交通运输工程", "link_text": "交通运输工程"},
                {"name": "水利工程", "link_text": "水利工程"},
                {"name": "其他工程", "link_text": "其他工程"},
            ],
        },
        SimpleNamespace(marks=[]),
        node_context={"category_path": "工程建设 > 房屋建筑和市政基础设施工程"},
    )

    assert result["page_type"] == "list_page"
    assert result["subtasks"] == []
    assert "不再继续向下拆分" in result["observations"]


def test_post_process_analysis_prunes_ancestor_backtrack_to_list_page():
    planner = TaskPlanner.__new__(TaskPlanner)
    planner.user_request = "采集网站中工程建设下各个相关分类的项目名称，每类10条"

    result = planner._post_process_analysis(
        {
            "page_type": "category",
            "name": "房屋建筑和市政基础设施工程列表",
            "task_description": "继续拆分分类",
            "observations": "当前已进入房屋建筑和市政基础设施工程。",
            "subtasks": [
                {"name": "工程建设", "link_text": "工程建设"},
            ],
        },
        SimpleNamespace(marks=[]),
        node_context={"category_path": "工程建设-房屋建筑和市政基础设施工程"},
    )

    assert result["page_type"] == "list_page"
    assert result["subtasks"] == []
    assert "回跳入口" in result["observations"]
