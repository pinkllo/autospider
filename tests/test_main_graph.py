from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autospider.graph.main_graph import build_main_graph, resolve_feedback_route


def test_resolve_feedback_route_maps_replan_to_plan_strategy_node() -> None:
    state = {"control": {"active_strategy": {"name": "replan"}}}

    assert resolve_feedback_route(state) == "plan_strategy_node"


def test_resolve_feedback_route_rejects_unknown_strategy() -> None:
    with pytest.raises(ValueError, match="unknown_feedback_route"):
        resolve_feedback_route({"control": {"active_strategy": {"name": "unexpected"}}})


def test_build_main_graph_inserts_planning_and_feedback_layers() -> None:
    graph = build_main_graph()
    compiled = graph.get_graph()
    node_names = set(compiled.nodes)
    edge_pairs = {(edge.source, edge.target) for edge in compiled.edges}

    assert "initialize_world_model_node" in node_names
    assert "plan_strategy_node" in node_names
    assert "monitor_dispatch_node" in node_names
    assert "update_world_model_node" in node_names
    assert ("chat_prepare_execution_handoff", "initialize_world_model_node") in edge_pairs
    assert ("initialize_world_model_node", "plan_strategy_node") in edge_pairs
    assert ("multi_dispatch_subgraph", "monitor_dispatch_node") in edge_pairs
    assert ("monitor_dispatch_node", "update_world_model_node") in edge_pairs
    assert ("multi_dispatch_subgraph", "aggregate_node") not in edge_pairs
