from __future__ import annotations

import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autospider.pipeline.helpers import build_execution_context
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
