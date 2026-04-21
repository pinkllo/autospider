from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import autospider.composition.graph.main_graph as main_graph_module
from autospider.contexts.planning.domain import TaskPlan
from autospider.contexts.planning.domain.runtime import SubTaskRuntimeState
from autospider.composition.graph.main_graph import build_main_graph, resolve_feedback_route
from autospider.composition.graph._multi_dispatch import build_multi_dispatch_subgraph


def _runtime_result(
    *,
    status: str,
    error: str = "",
    terminal_reason: str = "",
) -> SubTaskRuntimeState:
    return SubTaskRuntimeState.model_validate(
        {
            "subtask_id": "subtask_001",
            "status": status,
            "error": error,
            "summary": {"terminal_reason": terminal_reason},
        }
    )


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


def test_build_main_graph_runs_feedback_replan_cycle_through_update_world_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatch_rounds = {"count": 0}
    dispatch_strategy_names: list[str] = []
    aggregate_observation = {
        "round": 0,
        "strategy": "",
        "world_categories": [],
        "world_model_categories": [],
    }

    def route_entry_stub(state: dict[str, object]) -> dict[str, object]:
        return {}

    def chat_clarify_stub(state: dict[str, object]) -> dict[str, object]:
        return {"conversation": {"flow_state": "ready"}}

    def chat_history_match_stub(state: dict[str, object]) -> dict[str, object]:
        return {}

    def chat_review_task_stub(state: dict[str, object]) -> dict[str, object]:
        return {"conversation": {"review_state": "approved"}}

    def chat_prepare_execution_handoff_stub(
        state: dict[str, object],
    ) -> dict[str, object]:
        return {"node_status": "ok", "error": None}

    def initialize_world_model_stub(state: dict[str, object]) -> dict[str, object]:
        request_params = {"target_url_count": 1}
        return {
            "world": {
                "request_params": request_params,
                "failure_records": [],
                "world_model": {
                    "request_params": request_params,
                    "page_models": {},
                    "failure_records": [],
                    "success_criteria": request_params,
                },
            }
        }

    def plan_node_stub(state: dict[str, object]) -> dict[str, object]:
        control = dict(state.get("control") or {})
        return {
            "control": {
                **control,
                "current_plan": {"goal": "collect"},
                "task_plan": {"subtasks": [{"id": "subtask_001"}]},
                "plan_knowledge": "stub-plan",
                "stage_status": "ok",
            },
            "node_status": "ok",
            "error": None,
        }

    def multi_dispatch_stub(state: dict[str, object]) -> dict[str, object]:
        dispatch_rounds["count"] += 1
        control = dict(state.get("control") or {})
        active_strategy = str((control.get("active_strategy") or {}).get("name") or "")
        dispatch_strategy_names.append(active_strategy)
        is_first_round = dispatch_rounds["count"] == 1
        results = [
            _runtime_result(
                status="system_failure" if is_first_round else "business_failure",
                error=(
                    "dom changed while clicking next page"
                    if is_first_round
                    else "downstream api rejected payload"
                ),
            )
        ]
        summary = {
            "total": 1,
            "completed": 0,
            "business_failure": 0 if is_first_round else 1,
            "system_failure": 1 if is_first_round else 0,
        }
        return {
            "execution": {
                "subtask_results": results,
                "dispatch_summary": summary,
            },
            "control": {
                **control,
                "current_plan": {"goal": "collect"},
                "task_plan": {"subtasks": [{"id": "subtask_001"}]},
                "plan_knowledge": "stub-plan",
                "stage_status": "ok",
            },
            "node_status": "ok",
            "error": None,
        }

    def aggregate_stub(state: dict[str, object]) -> dict[str, object]:
        world = dict(state.get("world") or {})
        world_model = dict(world.get("world_model") or {})
        aggregate_observation["round"] = dispatch_rounds["count"]
        aggregate_observation["strategy"] = str(
            ((state.get("control") or {}).get("active_strategy") or {}).get("name") or ""
        )
        aggregate_observation["world_categories"] = [
            str(item.get("category") or "") for item in list(world.get("failure_records") or [])
        ]
        aggregate_observation["world_model_categories"] = [
            str(item.get("category") or "")
            for item in list(world_model.get("failure_records") or [])
        ]
        return {
            "result": {
                "status": "ok",
                "data": {"aggregate_result": {"round": dispatch_rounds["count"]}},
            }
        }

    monkeypatch.setattr(main_graph_module, "route_entry", route_entry_stub)
    monkeypatch.setattr(main_graph_module, "chat_clarify", chat_clarify_stub)
    monkeypatch.setattr(main_graph_module, "chat_history_match", chat_history_match_stub)
    monkeypatch.setattr(main_graph_module, "chat_review_task", chat_review_task_stub)
    monkeypatch.setattr(
        main_graph_module,
        "chat_prepare_execution_handoff",
        chat_prepare_execution_handoff_stub,
    )
    monkeypatch.setattr(
        main_graph_module,
        "initialize_world_model_node",
        initialize_world_model_stub,
    )
    monkeypatch.setattr(main_graph_module, "plan_node", plan_node_stub)
    monkeypatch.setattr(
        main_graph_module,
        "build_multi_dispatch_subgraph",
        lambda: multi_dispatch_stub,
    )
    monkeypatch.setattr(main_graph_module, "aggregate_node", aggregate_stub)

    graph = build_main_graph()

    final_state = graph.invoke(
        {
            "entry_mode": "chat_pipeline",
            "normalized_params": {"target_url_count": 1},
        }
    )

    assert dispatch_strategy_names == ["aggregate", "replan"]
    assert aggregate_observation["round"] == 2
    assert aggregate_observation["strategy"] == "aggregate"
    assert aggregate_observation["world_categories"] == ["fatal"]
    assert aggregate_observation["world_model_categories"] == ["fatal"]
    assert final_state["control"]["active_strategy"]["name"] == "aggregate"
    assert final_state["world"]["failure_records"][0]["category"] == "fatal"
    assert final_state["world"]["failure_records"][0]["metadata"]["message"] == (
        "downstream api rejected payload"
    )
    assert final_state["world"]["world_model"]["failure_records"][0]["category"] == "fatal"
    assert (
        final_state["world"]["world_model"]["failure_records"][0]["metadata"]["message"]
        == "downstream api rejected payload"
    )


@pytest.mark.asyncio
async def test_build_multi_dispatch_subgraph_accepts_control_task_plan_boundary() -> None:
    subgraph = build_multi_dispatch_subgraph()
    plan = TaskPlan(
        plan_id="plan_001",
        original_request="collect",
        site_url="https://example.com",
        subtasks=[],
        nodes=[],
        journal=[],
        total_subtasks=0,
        shared_fields=[],
        created_at="2026-04-12T00:00:00",
        updated_at="2026-04-12T00:00:00",
    )

    result = await subgraph.ainvoke(
        {
            "thread_id": "thread-1",
            "normalized_params": {"output_dir": "output"},
            "control": {
                "task_plan": plan,
                "plan_knowledge": "structured knowledge",
                "current_plan": {"goal": "collect"},
                "stage_status": "ok",
            },
            "execution": {"subtask_results": [], "dispatch_summary": {}},
        }
    )

    assert result["node_status"] == "ok"
    assert result["control"]["task_plan"].plan_id == "plan_001"
    assert result["execution"]["dispatch_summary"]["total"] == 0

