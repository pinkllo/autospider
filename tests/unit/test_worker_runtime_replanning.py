from __future__ import annotations

from types import SimpleNamespace

import pytest

from autospider.common.config import config
from autospider.crawler.collector.llm_decision import LLMDecisionMaker
from autospider.domain.planning import ExecutionBrief, SubTask, SubTaskMode
from autospider.pipeline import runner as runner_module
from autospider.pipeline import worker as worker_module
from autospider.pipeline.worker import SubTaskWorker
from autospider.crawler.planner.task_planner import RuntimeSubtaskPlanResult


class _FakeSession:
    def __init__(self, **kwargs):
        self.page = SimpleNamespace(url="https://example.com/list")

    async def start(self):
        return None

    async def stop(self):
        return None


@pytest.mark.asyncio
async def test_subtask_worker_expand_mode_spawns_runtime_children_without_collect(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    class _FakePlanner:
        def __init__(self, **kwargs):
            captured["planner_init"] = dict(kwargs)

        async def plan_runtime_subtasks(self, *, parent_subtask, max_children):
            captured["max_children"] = max_children
            child = SubTask(
                id="expand_child",
                name="交通运输工程",
                list_url="https://example.com/list",
                anchor_url="https://example.com/list",
                page_state_signature="state_child",
                task_description="爬取交通运输工程下各个相关分类的项目各10条。",
                parent_id=parent_subtask.id,
                depth=2,
                mode=SubTaskMode.EXPAND,
                execution_brief=ExecutionBrief(
                    parent_chain=["工程建设"],
                    current_scope="交通运输工程",
                ),
            )
            return RuntimeSubtaskPlanResult(page_type="category", analysis={}, children=[child])

    async def _unexpected_run_pipeline(**kwargs):
        raise AssertionError("expand 成功派生子任务后不应进入采集 pipeline")

    monkeypatch.setattr(worker_module, "BrowserSession", _FakeSession)
    monkeypatch.setattr(worker_module, "TaskPlanner", _FakePlanner)
    monkeypatch.setattr(runner_module, "run_pipeline", _unexpected_run_pipeline)
    monkeypatch.setattr(config.planner, "runtime_subtasks_max_children", 0, raising=False)

    worker = SubTaskWorker(
        subtask=SubTask(
            id="expand_parent",
            name="工程建设",
            list_url="https://example.com/list",
            anchor_url="https://example.com/list",
            page_state_signature="state_parent",
            task_description="爬取工程建设下各个相关分类的项目各10条。",
            context={"category_name": "工程建设", "category_path": "工程建设"},
            mode=SubTaskMode.EXPAND,
            execution_brief=ExecutionBrief(current_scope="工程建设"),
        ),
        fields=[],
        output_dir=str(tmp_path),
        headless=True,
    )

    result = await worker.execute()

    assert captured["max_children"] == 0
    assert result["execution_state"] == "expanded"
    assert result["total_urls"] == 0
    assert result["spawned_subtasks"][0]["parent_id"] == "expand_parent"
    assert result["spawned_subtasks"][0]["execution_brief"]["parent_chain"] == ["工程建设"]


@pytest.mark.asyncio
async def test_subtask_worker_expand_mode_converts_to_collect_and_runs_pipeline(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    class _FakePlanner:
        def __init__(self, **kwargs):
            return None

        async def plan_runtime_subtasks(self, *, parent_subtask, max_children):
            return RuntimeSubtaskPlanResult(
                page_type="list_page",
                analysis={"observations": "只剩兄弟切换"},
                collect_task_description="采集当前“房屋建筑和市政基础设施工程”范围下前10条项目记录，提取项目名称与所属分类名称。",
                collect_execution_brief=ExecutionBrief(
                    parent_chain=["工程建设"],
                    current_scope="房屋建筑和市政基础设施工程",
                    objective="采集当前房屋建筑和市政基础设施工程列表",
                    next_action="直接在当前页面收集详情链接并翻页，不再继续拆分分类。",
                    stop_rule="当无新详情链接、达到目标数量，或无法继续翻页时结束当前采集任务。",
                    do_not=["不要再把兄弟分类切换当作新的分类任务"],
                ),
            )

    async def _fake_run_pipeline(**kwargs):
        captured.update(kwargs)
        return {
            "items_file": str(tmp_path / "items.jsonl"),
            "total_urls": 2,
            "success_count": 2,
        }

    monkeypatch.setattr(worker_module, "BrowserSession", _FakeSession)
    monkeypatch.setattr(worker_module, "TaskPlanner", _FakePlanner)
    monkeypatch.setattr(runner_module, "run_pipeline", _fake_run_pipeline)

    worker = SubTaskWorker(
        subtask=SubTask(
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
        ),
        fields=[],
        output_dir=str(tmp_path),
        headless=True,
    )

    result = await worker.execute()

    assert captured["task_description"] == (
        "采集当前“房屋建筑和市政基础设施工程”范围下前10条项目记录，提取项目名称与所属分类名称。"
    )
    assert captured["execution_brief"]["current_scope"] == "房屋建筑和市政基础设施工程"
    assert captured["execution_brief"]["parent_chain"] == ["工程建设"]
    assert str(result["effective_subtask"]["mode"]) in {
        SubTaskMode.COLLECT.value,
        str(SubTaskMode.COLLECT),
    }
    assert [entry["action"] for entry in result["journal_entries"]] == [
        "runtime_leaf_confirmed",
        "runtime_expand_to_collect",
    ]


@pytest.mark.asyncio
async def test_llm_decision_prompt_contains_execution_brief(monkeypatch):
    captured: dict[str, object] = {}

    def _fake_render_template(path, section, variables=None):
        if section == "ask_llm_decision_user_message":
            captured["variables"] = dict(variables or {})
        return "prompt"

    class _FakeLLM:
        async def ainvoke(self, messages):
            return SimpleNamespace(content='{"action":"done","args":{}}')

    monkeypatch.setattr("autospider.crawler.collector.llm_decision.render_template", _fake_render_template)
    monkeypatch.setattr(
        "autospider.crawler.collector.llm_decision.parse_protocol_message",
        lambda response: {"action": "done", "args": {}},
    )

    decider = SimpleNamespace(llm=_FakeLLM())
    maker = LLMDecisionMaker(
        page=SimpleNamespace(url="https://example.com/list"),
        decider=decider,
        task_description="采集当前分类项目",
        collected_urls=[],
        visited_detail_urls=set(),
        list_url="https://example.com/list",
        execution_brief={
            "parent_chain": ["工程建设"],
            "current_scope": "交通运输工程",
            "stop_rule": "无下级相关分类时开始采集",
        },
    )

    result = await maker.ask_for_decision(SimpleNamespace(marks=[]), screenshot_base64="base64")

    assert result["action"] == "done"
    assert "交通运输工程" in captured["variables"]["execution_brief"]
    assert "工程建设" in captured["variables"]["execution_brief"]
    assert "无下级相关分类时开始采集" in captured["variables"]["execution_brief"]
