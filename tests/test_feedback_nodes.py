from __future__ import annotations

import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autospider.graph.nodes.feedback_nodes import (
    monitor_dispatch_node,
    update_world_model_node,
)
from autospider.graph.subgraphs.multi_dispatch import route_after_feedback


def test_monitor_dispatch_node_sets_replan_strategy_on_state_mismatch() -> None:
    state = {
        "world": {
            "failure_records": [
                {"page_id": "node_001", "category": "state_mismatch", "detail": "dom changed"},
            ]
        },
        "control": {"active_strategy": {"name": "aggregate"}},
    }

    result = monitor_dispatch_node(state)

    assert result["control"]["active_strategy"]["name"] == "replan"


def test_route_after_feedback_returns_replan_or_aggregate() -> None:
    replan_state = {"control": {"active_strategy": {"name": "replan"}}}
    aggregate_state = {"control": {"active_strategy": {"name": "aggregate"}}}

    assert route_after_feedback(replan_state) == "replan"
    assert route_after_feedback(aggregate_state) == "aggregate"


def test_update_world_model_node_syncs_feedback_failures() -> None:
    state = {
        "world": {
            "world_model": {
                "request_params": {"target_url_count": 3},
                "page_models": {},
                "failure_records": [],
                "success_criteria": {"target_url_count": 3},
            }
        },
        "feedback": {
            "failure_records": [
                {"page_id": "node_001", "category": "state_mismatch", "detail": "dom changed"},
            ]
        },
    }

    result = update_world_model_node(state)

    assert result["world"]["failure_records"][0]["category"] == "state_mismatch"
    assert result["world"]["world_model"]["failure_records"][0]["category"] == "state_mismatch"
