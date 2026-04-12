from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autospider.pipeline.helpers import build_execution_context
from autospider.pipeline.runner import run_pipeline
from autospider.pipeline.types import ExecutionRequest
from autospider.graph.control_types import (
    build_default_dispatch_policy,
    build_default_recovery_policy,
)
from autospider.graph.decision_context import build_decision_context
from autospider.graph.world_model import build_initial_world_model, upsert_page_model


def test_execution_request_from_params_preserves_decision_payloads() -> None:
    params = {
        "list_url": "https://example.com/articles",
        "decision_context": {
            "page_model": {"page_id": "entry", "page_type": "list_page"},
        },
        "world_snapshot": {
            "page_models": {"entry": {"page_type": "list_page"}},
        },
        "failure_records": [
            {"page_id": "entry", "category": "navigation", "detail": "timed_out"}
        ],
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
    import autospider.pipeline.runner as runner_module

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
    monkeypatch.setattr(runner_module, "SkillRuntime", lambda: object())
    monkeypatch.setattr(runner_module, "TaskProgressTracker", _FakeTracker)
    monkeypatch.setattr(runner_module, "_prepare_pipeline_output", lambda **_kwargs: None)
    monkeypatch.setattr(runner_module, "_persist_run_snapshot", lambda **_kwargs: None)
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
    assert finalization_context.site_profile_snapshot == {"host": "example.com", "supports_pagination": True}
    assert finalization_context.failure_records == [{"category": "rule_stale", "detail": "selector stale"}]
    assert finalization_context.failure_patterns == [{"pattern_id": "loop-detected", "trigger": "ABAB loop"}]
