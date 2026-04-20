from __future__ import annotations

import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import pytest
from langgraph.graph import END, StateGraph

from autospider.contexts.planning.domain.runtime import SubTaskRuntimeState
from autospider.composition.legacy.graph.nodes.feedback_nodes import (
    monitor_dispatch_node,
    update_world_model_node,
)
from autospider.composition.legacy.graph.nodes.planning_nodes import plan_strategy_node
from autospider.composition.legacy.graph.state import GraphState
from autospider.composition.legacy.graph.subgraphs.multi_dispatch import route_after_feedback


def _system_failure_result(*, error: str, terminal_reason: str = "") -> SubTaskRuntimeState:
    return SubTaskRuntimeState.model_validate(
        {
            "subtask_id": "subtask_001",
            "status": "system_failure",
            "error": error,
            "summary": {"terminal_reason": terminal_reason},
        }
    )


def test_monitor_dispatch_node_sets_replan_strategy_from_current_dispatch_failure() -> None:
    state = {
        "execution": {
            "subtask_results": [
                _system_failure_result(error="dom changed while clicking next page"),
            ]
        },
        "control": {"active_strategy": {"name": "aggregate"}},
    }

    result = monitor_dispatch_node(state)

    assert result["control"]["active_strategy"]["name"] == "replan"
    assert result["world"]["failure_records"][0]["category"] == "state_mismatch"


def test_route_after_feedback_returns_replan_or_aggregate() -> None:
    replan_state = {"control": {"active_strategy": {"name": "replan"}}}
    aggregate_state = {"control": {"active_strategy": {"name": "aggregate"}}}

    assert route_after_feedback(replan_state) == "replan"
    assert route_after_feedback(aggregate_state) == "aggregate"


def test_route_after_feedback_rejects_unknown_strategy() -> None:
    with pytest.raises(ValueError, match="unknown_feedback_route"):
        route_after_feedback({"control": {"active_strategy": {"name": "unexpected"}}})


def test_plan_strategy_node_rejects_unknown_explicit_strategy() -> None:
    with pytest.raises(ValueError, match="unknown_active_strategy"):
        plan_strategy_node({"control": {"active_strategy": {"name": "surprise"}}})


def test_update_world_model_node_syncs_world_failures_without_feedback_key() -> None:
    state = {
        "world": {
            "world_model": {
                "request_params": {"target_url_count": 3},
                "page_models": {},
                "failure_records": [],
                "success_criteria": {"target_url_count": 3},
            },
            "failure_records": [
                {"page_id": "node_001", "category": "state_mismatch", "detail": "dom changed"},
            ],
        },
    }

    result = update_world_model_node(state)

    assert result["world"]["failure_records"][0]["category"] == "state_mismatch"
    assert result["world"]["world_model"]["failure_records"][0]["category"] == "state_mismatch"


def test_monitor_and_update_nodes_share_data_through_declared_namespaces() -> None:
    graph = StateGraph(GraphState)
    graph.add_node("monitor_dispatch_node", monitor_dispatch_node)
    graph.add_node("update_world_model_node", update_world_model_node)
    graph.set_entry_point("monitor_dispatch_node")
    graph.add_edge("monitor_dispatch_node", "update_world_model_node")
    graph.add_edge("update_world_model_node", END)
    app = graph.compile()

    result = app.invoke(
        {
            "execution": {
                "subtask_results": [
                    _system_failure_result(
                        error="",
                        terminal_reason="selector stale on detail page",
                    ),
                ]
            },
            "world": {
                "world_model": {
                    "request_params": {"target_url_count": 3},
                    "page_models": {},
                    "failure_records": [],
                    "success_criteria": {"target_url_count": 3},
                }
            },
        }
    )

    assert "feedback" not in result
    assert result["world"]["failure_records"][0]["category"] == "rule_stale"
