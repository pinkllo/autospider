from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autospider.legacy.pipeline.helpers import build_execution_context
from autospider.legacy.pipeline.runner import run_pipeline
from autospider.legacy.pipeline.types import ExecutionRequest
from autospider.legacy.pipeline.worker import SubTaskWorker
from autospider.legacy.graph.subgraphs.multi_dispatch import run_subtask_worker_node
from autospider.legacy.graph.control_types import (
    build_default_dispatch_policy,
    build_default_recovery_policy,
)
from autospider.legacy.graph.decision_context import build_decision_context
from autospider.contexts.planning.domain import ExecutionBrief, SubTask, SubTaskMode, TaskPlan
from autospider.legacy.graph.world_model import build_initial_world_model, upsert_page_model


def test_execution_request_from_params_preserves_decision_payloads() -> None:
    params = {
        "list_url": "https://example.com/articles",
        "decision_context": {
            "page_model": {"page_id": "entry", "page_type": "list_page"},
        },
        "world_snapshot": {
            "page_models": {"entry": {"page_type": "list_page"}},
        },
        "failure_records": [{"page_id": "entry", "category": "navigation", "detail": "timed_out"}],
    }

    request = ExecutionRequest.from_params(params, thread_id="thread-1")

    assert request.decision_context == params["decision_context"]
    assert request.world_snapshot == params["world_snapshot"]
    assert request.failure_records == params["failure_records"]


def test_build_execution_context_carries_decision_payloads_into_runtime_context() -> None:
    request = ExecutionRequest.from_params(
        {
            "list_url": "https://example.com/articles",
            "decision_context": {"page_model": {"page_type": "list_page"}},
            "world_snapshot": {"page_models": {"entry": {"page_type": "list_page"}}},
            "failure_records": [{"category": "navigation"}],
        },
        thread_id="thread-1",
    )

    context = build_execution_context(request)

    assert context.decision_context == {"page_model": {"page_type": "list_page"}}
    assert context.world_snapshot == {"page_models": {"entry": {"page_type": "list_page"}}}
    assert context.failure_records == ({"category": "navigation"},)


def test_build_execution_context_reconciles_stale_explicit_semantic_signature() -> None:
    request = ExecutionRequest.from_params(
        {
            "list_url": "https://example.com/majors",
            "task_description": "按学科分类采集专业列表",
            "fields": [{"name": "title", "description": "专业名称", "required": True}],
            "group_by": "category",
            "per_group_target_count": 10,
            "total_target_count": 100,
            "category_discovery_mode": "auto",
            "requested_categories": [],
            "category_examples": ["交通运输工程"],
            "semantic_signature": "stale-semantic-signature",
        },
        thread_id="thread-1",
    )

    context = build_execution_context(request)
    expected_signature = build_execution_context(
        ExecutionRequest.from_params(
            {
                "list_url": "https://example.com/majors",
                "task_description": "按学科分类采集专业列表",
                "fields": [{"name": "title", "description": "专业名称", "required": True}],
                "group_by": "category",
                "per_group_target_count": 10,
                "total_target_count": 100,
                "category_discovery_mode": "auto",
                "requested_categories": [],
                "category_examples": ["交通运输工程"],
            },
            thread_id="thread-1",
        )
    ).identity.semantic_signature

    assert context.identity.semantic_signature == expected_signature


def test_execution_request_accepts_build_decision_context_payload_directly() -> None:
    world_model = build_initial_world_model(
        request_params={"list_url": "https://example.com/articles", "target_url_count": 8}
    )
    world_model = upsert_page_model(
        world_model,
        page_id="entry",
        url="https://example.com/articles",
        page_type="list_page",
        links=12,
    )
    workflow = {
        "world": {
            "world_model": world_model,
            "failure_records": [
                {"page_id": "entry", "category": "navigation", "detail": "timed_out"}
            ],
        },
        "control": {
            "dispatch_policy": build_default_dispatch_policy(),
            "recovery_policy": build_default_recovery_policy(),
        },
    }

    decision_context = build_decision_context(workflow, page_id="entry")
    request = ExecutionRequest.from_params(
        {
            "list_url": "https://example.com/articles",
            "decision_context": decision_context,
            "failure_records": decision_context["recent_failures"],
        },
        thread_id="thread-1",
    )

    assert request.decision_context["page_model"]["page_type"] == "list_page"
    assert request.failure_records == [
        {"page_id": "entry", "category": "navigation", "detail": "timed_out", "metadata": {}}
    ]


def test_runtime_context_prefers_workflow_payloads_over_legacy_compat_fields() -> None:
    world_model = build_initial_world_model(
        request_params={"list_url": "https://example.com/articles", "target_url_count": 8}
    )
    world_model = upsert_page_model(
        world_model,
        page_id="entry",
        url="https://example.com/articles",
        page_type="list_page",
        links=12,
    )
    workflow = {
        "world": {
            "world_model": world_model,
            "failure_records": [
                {"page_id": "entry", "category": "navigation", "detail": "timed_out"}
            ],
        },
        "control": {
            "dispatch_policy": build_default_dispatch_policy(),
            "recovery_policy": build_default_recovery_policy(),
        },
    }
    decision_context = build_decision_context(workflow, page_id="entry")
    workflow_failure_records = decision_context["recent_failures"]
    world_snapshot = dict(workflow["world"])
    world_snapshot["request_params"] = {
        "decision_context": decision_context,
        "failure_records": workflow_failure_records,
    }

    request = ExecutionRequest.from_params(
        {
            "list_url": "https://example.com/articles",
            "decision_context": {"page_model": {"page_type": "detail_page"}},
            "failure_records": [{"page_id": "legacy", "category": "compat", "detail": "stale"}],
            "world_snapshot": world_snapshot,
        },
        thread_id="thread-1",
    )

    context = build_execution_context(request)

    assert request.decision_context == decision_context
    assert request.failure_records == workflow_failure_records
    assert context.decision_context == decision_context
    assert context.failure_records == tuple(workflow_failure_records)


@pytest.mark.asyncio
async def test_run_pipeline_passes_learning_snapshots_into_finalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import autospider.legacy.pipeline.runner as runner_module

    captured: dict[str, object] = {}

    class _FakeChannel:
        async def close(self) -> None:
            return None

    class _FakeSession:
        def __init__(self, **_kwargs) -> None:
            self.page = SimpleNamespace(url="https://example.com/list")

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

    class _FakeTracker:
        def __init__(self, *_args, **_kwargs) -> None:
            return None

        async def set_runtime_state(self, _payload: dict[str, object]) -> None:
            return None

    class _FakeFinalizer:
        def __init__(self, _deps) -> None:
            return None

        async def finalize(self, context) -> None:
            captured["context"] = context

    class _FakeRunner:
        async def run(self) -> None:
            return None

    monkeypatch.setattr(runner_module, "create_url_channel", lambda **_kwargs: _FakeChannel())
    monkeypatch.setattr(runner_module, "BrowserRuntimeSession", _FakeSession)
    monkeypatch.setattr(runner_module, "SkillRuntime", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(runner_module, "TaskProgressTracker", _FakeTracker)
    monkeypatch.setattr(runner_module, "_prepare_pipeline_output", lambda **_kwargs: None)

    async def _fake_persist_run_snapshot(**_kwargs) -> None:
        return None

    monkeypatch.setattr(runner_module, "_persist_run_snapshot", _fake_persist_run_snapshot)
    monkeypatch.setattr(runner_module, "_load_persisted_run_records", lambda _execution_id: {})
    monkeypatch.setattr(
        runner_module,
        "create_pipeline_services",
        lambda _context, _deps: SimpleNamespace(
            producer=_FakeRunner(),
            consumer_pool=_FakeRunner(),
        ),
    )
    monkeypatch.setattr(runner_module, "PipelineFinalizer", _FakeFinalizer)

    workflow_world_snapshot = {
        "request_params": {
            "decision_context": {"page_model": {"page_type": "list_page"}},
            "failure_records": [{"category": "rule_stale", "detail": "selector stale"}],
        },
        "site_profile": {"host": "example.com", "supports_pagination": True},
        "failure_patterns": [{"pattern_id": "loop-detected", "trigger": "ABAB loop"}],
        "world_model": {"page_models": {"entry": {"page_type": "list_page"}}},
    }

    request = ExecutionRequest.from_params(
        {
            "list_url": "https://example.com/list",
            "task_description": "collect products",
            "output_dir": "output/test-runner-learning-snapshots",
            "world_snapshot": workflow_world_snapshot,
            "failure_records": [{"category": "legacy", "detail": "ignored"}],
        },
        thread_id="thread-1",
    )
    context = build_execution_context(request)

    await run_pipeline(context)

    finalization_context = captured["context"]
    assert finalization_context.world_snapshot == workflow_world_snapshot
    assert finalization_context.site_profile_snapshot == {
        "host": "example.com",
        "supports_pagination": True,
    }
    assert finalization_context.failure_records == [
        {"category": "rule_stale", "detail": "selector stale"}
    ]
    assert finalization_context.failure_patterns == [
        {"pattern_id": "loop-detected", "trigger": "ABAB loop"}
    ]


def test_subtask_worker_prepare_fields_prefers_fixed_fields_for_category_like_values() -> None:
    subtask = SubTask(
        id="leaf_001",
        name="交通运输工程",
        list_url="https://example.com/majors/traffic",
        task_description="采集交通运输工程专业列表",
        context={"category_name": "页面上下文中的旧值"},
        scope={"key": "category:工学 > 交通运输工程", "label": "工学 > 交通运输工程"},
        fixed_fields={"所属分类": "工学-交通运输工程", "category_name": "工学-交通运输工程"},
        mode=SubTaskMode.COLLECT,
        execution_brief=ExecutionBrief(objective="采集交通运输工程"),
    )
    worker = SubTaskWorker(
        subtask=subtask,
        fields=[
            {"name": "所属分类", "description": "该记录所属分类", "required": True},
            {"name": "标题", "description": "记录标题", "required": True},
        ],
    )

    prepared = worker._prepare_fields()

    category_field = next(field for field in prepared if field.name == "所属分类")
    title_field = next(field for field in prepared if field.name == "标题")
    assert category_field.extraction_source == "subtask_context"
    assert category_field.fixed_value == "工学-交通运输工程"
    assert title_field.extraction_source in (None, "")
    assert title_field.fixed_value in (None, "")


def test_subtask_worker_prepare_fields_overrides_upstream_category_extraction_with_scoped_value() -> (
    None
):
    subtask = SubTask(
        id="leaf_001",
        name="交通运输工程",
        list_url="https://example.com/majors/traffic",
        task_description="采集交通运输工程专业列表",
        scope={"key": "category:工学 > 交通运输工程", "label": "工学 > 交通运输工程"},
        fixed_fields={"所属分类": "工学-交通运输工程"},
        mode=SubTaskMode.COLLECT,
        execution_brief=ExecutionBrief(objective="采集交通运输工程"),
    )
    worker = SubTaskWorker(
        subtask=subtask,
        fields=[
            {
                "name": "所属分类",
                "description": "该记录所属分类",
                "required": True,
                "extraction_source": "detail_page",
                "fixed_value": "详情页猜测值",
            }
        ],
    )

    prepared = worker._prepare_fields()

    assert prepared[0].extraction_source == "subtask_context"
    assert prepared[0].fixed_value == "工学-交通运输工程"


def test_subtask_worker_prepare_fields_uses_scope_when_fixed_fields_are_missing() -> None:
    subtask = SubTask(
        id="leaf_001",
        name="交通运输工程",
        list_url="https://example.com/majors/traffic",
        task_description="采集交通运输工程专业列表",
        scope={
            "key": "category:工学 > 交通运输工程",
            "label": "工学 > 交通运输工程",
            "path": ["工学", "交通运输工程"],
        },
        mode=SubTaskMode.COLLECT,
        execution_brief=ExecutionBrief(objective="采集交通运输工程"),
    )
    worker = SubTaskWorker(
        subtask=subtask,
        fields=[{"name": "分类", "description": "该记录所属分类", "required": True}],
    )

    prepared = worker._prepare_fields()

    assert prepared[0].extraction_source == "subtask_context"
    assert prepared[0].fixed_value == "工学 > 交通运输工程"


def test_subtask_worker_prepare_fields_does_not_override_non_category_fields() -> None:
    subtask = SubTask(
        id="leaf_001",
        name="交通运输工程",
        list_url="https://example.com/majors/traffic",
        task_description="采集交通运输工程专业列表",
        scope={
            "key": "category:工学 > 交通运输工程",
            "label": "工学 > 交通运输工程",
            "path": ["工学", "交通运输工程"],
        },
        fixed_fields={"所属分类": "工学 > 交通运输工程"},
        mode=SubTaskMode.COLLECT,
        execution_brief=ExecutionBrief(objective="采集交通运输工程"),
    )
    worker = SubTaskWorker(
        subtask=subtask,
        fields=[
            {
                "name": "公告类型",
                "description": "公告业务类型",
                "required": True,
                "extraction_source": "detail_page",
                "fixed_value": "招标公告",
            },
            {
                "name": "项目标签",
                "description": "项目标签列表",
                "required": True,
                "extraction_source": "detail_page",
                "fixed_value": "交通,省级",
            },
        ],
    )

    prepared = worker._prepare_fields()

    notice_type = next(field for field in prepared if field.name == "公告类型")
    project_tags = next(field for field in prepared if field.name == "项目标签")
    assert notice_type.extraction_source == "detail_page"
    assert notice_type.fixed_value == "招标公告"
    assert project_tags.extraction_source == "detail_page"
    assert project_tags.fixed_value == "交通,省级"


@pytest.mark.asyncio
async def test_run_subtask_worker_node_uses_per_subtask_target_count_when_global_target_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import autospider.legacy.graph.subgraphs.multi_dispatch as dispatch_module

    captured: dict[str, object] = {}

    class _FakeWorker:
        def __init__(self, *, subtask, **_kwargs) -> None:
            captured["target_url_count"] = subtask.target_url_count

        async def execute(self) -> dict[str, object]:
            return {
                "total_urls": 1,
                "success_count": 1,
                "failed_count": 0,
                "outcome_state": "success",
                "execution_state": "completed",
                "durability_state": "durable",
                "execution_id": "exec-1",
                "items_file": "",
                "summary_file": "",
            }

    monkeypatch.setattr(dispatch_module, "SubTaskWorker", _FakeWorker)

    subtask = SubTask(
        id="leaf_001",
        name="交通运输工程",
        list_url="https://example.com/majors/traffic",
        task_description="采集交通运输工程专业列表",
        per_subtask_target_count=3,
        mode=SubTaskMode.COLLECT,
        execution_brief=ExecutionBrief(objective="采集交通运输工程"),
    )
    plan = TaskPlan(
        plan_id="plan_001",
        original_request="每类前 3 条",
        site_url="https://example.com/majors",
        subtasks=[subtask],
    )

    await run_subtask_worker_node(
        {
            "normalized_params": {"output_dir": "output/test-task3"},
            "task_plan": plan,
            "plan_knowledge": "",
            "subtask_payload": subtask.model_dump(mode="python"),
        }
    )

    assert captured["target_url_count"] == 3


@pytest.mark.asyncio
async def test_run_subtask_worker_node_prefers_per_subtask_target_count_for_grouped_category_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import autospider.legacy.graph.subgraphs.multi_dispatch as dispatch_module

    captured: dict[str, object] = {}

    class _FakeWorker:
        def __init__(self, *, subtask, **_kwargs) -> None:
            captured["target_url_count"] = subtask.target_url_count

        async def execute(self) -> dict[str, object]:
            return {
                "total_urls": 1,
                "success_count": 1,
                "failed_count": 0,
                "outcome_state": "success",
                "execution_state": "completed",
                "durability_state": "durable",
                "execution_id": "exec-1",
                "items_file": "",
                "summary_file": "",
            }

    monkeypatch.setattr(dispatch_module, "SubTaskWorker", _FakeWorker)

    subtask = SubTask(
        id="leaf_001",
        name="交通运输工程",
        list_url="https://example.com/majors/traffic",
        task_description="采集交通运输工程专业列表",
        scope={
            "key": "category:工学 > 交通运输工程",
            "label": "工学 > 交通运输工程",
            "path": ["工学", "交通运输工程"],
        },
        per_subtask_target_count=3,
        mode=SubTaskMode.COLLECT,
        execution_brief=ExecutionBrief(objective="采集交通运输工程"),
    )
    plan = TaskPlan(
        plan_id="plan_001",
        original_request="每类前 3 条",
        site_url="https://example.com/majors",
        subtasks=[subtask],
    )

    await run_subtask_worker_node(
        {
            "normalized_params": {
                "output_dir": "output/test-task3",
                "target_url_count": 12,
            },
            "task_plan": plan,
            "plan_knowledge": "",
            "subtask_payload": subtask.model_dump(mode="python"),
        }
    )

    assert captured["target_url_count"] == 3
