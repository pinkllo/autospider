from __future__ import annotations

import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autospider.pipeline.helpers import build_execution_context
from autospider.pipeline.types import ExecutionRequest


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
