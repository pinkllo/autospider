from __future__ import annotations

import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autospider.graph.control_types import (
    build_default_dispatch_policy,
    build_default_recovery_policy,
)
from autospider.graph.decision_context import build_decision_context
from autospider.graph.world_model import build_initial_world_model, upsert_page_model


def test_build_default_policies_expose_control_contract_defaults() -> None:
    dispatch_policy = build_default_dispatch_policy()
    recovery_policy = build_default_recovery_policy()

    assert dispatch_policy.max_concurrency == 1
    assert dispatch_policy.strategy == "sequential"
    assert recovery_policy.max_retries == 2
    assert recovery_policy.fail_fast is True


def test_build_decision_context_reads_world_model_failures_and_success_criteria() -> None:
    world_model = build_initial_world_model(
        request_params={
            "list_url": "https://example.com/articles",
            "target_url_count": 8,
        }
    )
    world_model = upsert_page_model(
        world_model,
        page_id="entry",
        url="https://example.com/articles",
        page_type="list_page",
        links=14,
    )
    workflow = {
        "world": {
            "world_model": world_model,
            "failure_records": [
                {
                    "page_id": "entry",
                    "category": "navigation",
                    "detail": "timed_out",
                }
            ],
        },
        "control": {
            "dispatch_policy": build_default_dispatch_policy(),
            "recovery_policy": build_default_recovery_policy(),
        },
    }

    context = build_decision_context(workflow, page_id="entry")

    assert context.page_model.page_type == "list_page"
    assert context.recent_failures[0].category == "navigation"
    assert context.success_criteria.target_url_count == 8
