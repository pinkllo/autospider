from __future__ import annotations

from types import SimpleNamespace

import pytest

from autospider.common.config import config
from autospider.crawler.collector.llm_decision import LLMDecisionMaker
from autospider.contracts import ExpandRequest
from autospider.domain.planning import ExecutionBrief, SubTask, SubTaskMode
from autospider.pipeline import runner as runner_module
from autospider.pipeline import worker as worker_module
from autospider.pipeline.worker import SubTaskWorker
from autospider.services.runtime_expansion_service import RuntimeExpansionResult


@pytest.mark.asyncio
async def test_subtask_worker_expand_mode_spawns_runtime_children_without_collect(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    class _FakeRuntimeExpansionService:
        async def expand(self, **kwargs):
            captured["max_children"] = kwargs["max_children"]
            child = SubTask(
                id="expand_child",
                name="交通运输工程",
                list_url="https://example.com/list",
                anchor_url="https://example.com/list",
                page_state_signature="state_child",
                task_description="爬取交通运输工程下各个相关分类的项目各10条。",
                parent_id=kwargs["subtask"].id,
                depth=2,
                mode=SubTaskMode.EXPAND,
                execution_brief=ExecutionBrief(
                    parent_chain=["工程建设"],
                    current_scope="交通运输工程",
                ),
            )
            return RuntimeExpansionResult(
                execution_state="expanded",
                effective_subtask=kwargs["subtask"],
                journal_entries=(),
                expand_request=ExpandRequest(
                    parent_subtask_id=kwargs["subtask"].id,
                    spawned_subtasks=(child.model_dump(mode="python"),),
                    journal_entries=(),
                    reason="runtime_expand",
                ),
            )

    async def _unexpected_run_pipeline(_context):
        raise AssertionError("expand 成功派生子任务后不应进入采集 pipeline")

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
        runtime_expansion_service_cls=_FakeRuntimeExpansionService,
    )

    result = await worker.execute()

    assert captured["max_children"] == 0
    assert result["execution_state"] == "expanded"
    assert result["outcome_type"] == "expanded"
    assert result["total_urls"] == 0
    assert result["expand_request"]["spawned_subtasks"][0]["parent_id"] == "expand_parent"
    assert result["expand_request"]["spawned_subtasks"][0]["execution_brief"]["parent_chain"] == ["工程建设"]


@pytest.mark.asyncio
async def test_subtask_worker_expand_mode_converts_to_collect_and_runs_pipeline(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    class _FakeRuntimeExpansionService:
        async def expand(self, **kwargs):
            collect_subtask = kwargs["subtask"].model_copy(
                update={
                    "mode": SubTaskMode.COLLECT,
                    "task_description": "采集当前“房屋建筑和市政基础设施工程”范围下前10条项目记录，提取项目名称与所属分类名称。",
                    "execution_brief": ExecutionBrief(
                        parent_chain=["工程建设"],
                        current_scope="房屋建筑和市政基础设施工程",
                        objective="采集当前房屋建筑和市政基础设施工程列表",
                        next_action="直接在当前页面收集详情链接并翻页，不再继续拆分分类。",
                        stop_rule="当无新详情链接、达到目标数量，或无法继续翻页时结束当前采集任务。",
                        do_not=["不要再把兄弟分类切换当作新的分类任务"],
                    ),
                }
            )
            return RuntimeExpansionResult(
                execution_state="collect",
                effective_subtask=collect_subtask,
                journal_entries=(
                    {
                        "entry_id": "",
                        "node_id": "",
                        "phase": "pipeline",
                        "action": "runtime_leaf_confirmed",
                        "reason": "当前任务未识别到更深相关分类，确认为叶子采集任务",
                        "evidence": "只剩兄弟切换",
                        "metadata": {},
                        "created_at": "",
                    },
                    {
                        "entry_id": "",
                        "node_id": "",
                        "phase": "pipeline",
                        "action": "runtime_expand_to_collect",
                        "reason": "expand 任务就地转为 collect 执行",
                        "evidence": "采集当前“房屋建筑和市政基础设施工程”范围下前10条项目记录，提取项目名称与所属分类名称。",
                        "metadata": {"mode": SubTaskMode.COLLECT.value},
                        "created_at": "",
                    },
                ),
            )

    async def _fake_run_pipeline(context):
        captured.update(context.request.model_dump(mode="python"))
        return {
            "items_file": str(tmp_path / "items.jsonl"),
            "total_urls": 2,
            "success_count": 2,
            "outcome_state": "success",
            "durability_state": "durable",
        }

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
        runtime_expansion_service_cls=_FakeRuntimeExpansionService,
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
