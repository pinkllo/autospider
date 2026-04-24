from __future__ import annotations

import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import pytest
from langgraph.graph import END, StateGraph

from autospider.contexts.planning.domain.runtime import SubTaskRuntimeState
from autospider.composition.graph.nodes.feedback_nodes import (
    monitor_dispatch_node,
    update_world_model_node,
)
from autospider.composition.graph.nodes.planning_nodes import plan_strategy_node
from autospider.composition.graph.state import GraphState
from autospider.composition.graph._multi_dispatch import route_after_feedback
from autospider.composition.graph.world_model import (
    resolve_list_profile_candidates_from_world,
)


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


def test_update_world_model_node_merges_validated_profiles_by_variant() -> None:
    state = {
        "world": {
            "world_model": {
                "request_params": {"target_url_count": 3},
                "page_models": {
                    "node_001": {"page_id": "node_001", "page_type": "list_page", "metadata": {}}
                },
                "failure_records": [],
                "success_criteria": {"target_url_count": 3},
            },
        },
        "execution": {
            "subtask_results": [
                {
                    "subtask_id": "subtask_001",
                    "effective_subtask": {"plan_node_id": "node_001"},
                    "collection_config": {
                        "profile_key": "key-a",
                        "profile_validation_status": "validated",
                        "anchor_url": "https://example.com/root",
                        "page_state_signature": "sig-list",
                        "variant_label": "采购公告",
                        "task_description": "采集详情链接",
                        "common_detail_xpath": "//a[@class='purchase']",
                    },
                },
                {
                    "subtask_id": "subtask_002",
                    "effective_subtask": {"plan_node_id": "node_001"},
                    "collection_config": {
                        "profile_key": "key-b",
                        "profile_validation_status": "validated",
                        "anchor_url": "https://example.com/root",
                        "page_state_signature": "sig-list",
                        "variant_label": "中标公告",
                        "task_description": "采集详情链接",
                        "common_detail_xpath": "//a[@class='award']",
                    },
                },
            ]
        },
    }

    result = update_world_model_node(state)
    profiles = result["world"]["world_model"]["page_models"]["node_001"]["metadata"]["list_page_profile"]

    assert profiles["key-a"]["variant_label"] == "采购公告"
    assert profiles["key-b"]["variant_label"] == "中标公告"


def test_update_world_model_node_ignores_rejected_profile() -> None:
    state = {
        "world": {
            "world_model": {
                "request_params": {},
                "page_models": {"node_001": {"page_id": "node_001", "metadata": {}}},
                "failure_records": [],
            }
        },
        "execution": {
            "subtask_results": [
                {
                    "subtask_id": "subtask_001",
                    "effective_subtask": {"plan_node_id": "node_001"},
                    "collection_config": {
                        "profile_key": "reject-a",
                        "profile_validation_status": "rejected",
                        "profile_reject_reason": "xpath_no_match",
                        "common_detail_xpath": "//a",
                    },
                }
            ]
        },
    }

    result = update_world_model_node(state)
    metadata = result["world"]["world_model"]["page_models"]["node_001"]["metadata"]

    assert metadata.get("list_page_profile") is None
    assert metadata.get("detail_field_profiles") == []


def test_update_world_model_node_merges_detail_field_profiles_from_success_evidence() -> None:
    state = {
        "world": {
            "world_model": {
                "request_params": {},
                "page_models": {"node_001": {"page_id": "node_001", "metadata": {}}},
                "failure_records": [],
            }
        },
        "execution": {
            "subtask_results": [
                {
                    "subtask_id": "subtask_001",
                    "effective_subtask": {"plan_node_id": "node_001"},
                    "extraction_evidence": [
                        {
                            "url": "https://example.com/detail/1",
                            "success": True,
                            "extraction_config": {
                                "fields": [
                                    {
                                        "name": "title",
                                        "xpath": "//h1/text()",
                                        "xpath_validated": True,
                                        "detail_template_signature": "detail-v1",
                                        "field_signature": "title-v1",
                                        "extraction_source": "page",
                                    }
                                ]
                            },
                        }
                    ],
                }
            ]
        },
    }

    result = update_world_model_node(state)
    profiles = result["world"]["world_model"]["page_models"]["node_001"]["metadata"]["detail_field_profiles"]

    assert profiles[0]["field_name"] == "title"
    assert profiles[0]["xpath"] == "//h1/text()"
    assert profiles[0]["detail_template_signature"] == "detail-v1"


def test_update_world_model_node_skips_failed_detail_field_evidence() -> None:
    state = {
        "world": {
            "world_model": {
                "request_params": {},
                "page_models": {"node_001": {"page_id": "node_001", "metadata": {}}},
                "failure_records": [],
            }
        },
        "execution": {
            "subtask_results": [
                {
                    "subtask_id": "subtask_001",
                    "effective_subtask": {"plan_node_id": "node_001"},
                    "extraction_evidence": [
                        {
                            "url": "https://example.com/detail/1",
                            "success": False,
                            "extraction_config": {
                                "fields": [
                                    {
                                        "name": "title",
                                        "xpath": "//h1/text()",
                                        "xpath_validated": False,
                                        "detail_template_signature": "detail-v1",
                                        "field_signature": "title-v1",
                                    }
                                ]
                            },
                        }
                    ],
                }
            ]
        },
    }

    result = update_world_model_node(state)
    metadata = result["world"]["world_model"]["page_models"]["node_001"]["metadata"]

    assert metadata.get("detail_field_profiles") == []



def test_resolve_list_profile_candidates_from_world_keeps_only_xpath_candidates() -> None:
    world_snapshot = {
        "world_model": {
            "page_models": {
                "node_001": {
                    "page_id": "node_001",
                    "metadata": {
                        "list_page_profile": {
                            "candidate-no-xpath": {
                                "profile_key": "candidate-no-xpath",
                                "task_description": "完全匹配但没 xpath",
                                "page_state_signature": "sig-hit",
                                "common_detail_xpath": "",
                            },
                            "candidate-with-xpath": {
                                "profile_key": "candidate-with-xpath",
                                "task_description": "不相干描述",
                                "page_state_signature": "sig-other",
                                "common_detail_xpath": "//a[@class='detail']",
                            },
                        }
                    },
                }
            }
        }
    }

    candidates = resolve_list_profile_candidates_from_world(
        world_snapshot,
        page_id="node_001",
        page_state_signature="sig-hit",
        anchor_url="https://example.com/root",
        variant_label="采购公告",
        task_description="采集详情链接",
    )

    assert len(candidates) == 1
    assert candidates[0]["profile_key"] == "candidate-with-xpath"
