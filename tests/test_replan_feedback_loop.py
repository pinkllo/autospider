"""Phase-1 regression tests for the typed failure feedback loop.

Covers:
- Monitor routing on typed ``failure_category`` vs. string fallback.
- Replan budget degradation and counter transparency.
- ``active_strategy`` preservation through ``plan_node``.
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


from autospider.contexts.planning.domain.runtime import SubTaskRuntimeState
from autospider.legacy.graph.nodes.feedback_nodes import (
    REPLAN_BUDGET_EXHAUSTED_REASON,
    monitor_dispatch_node,
)
from autospider.legacy.graph.subgraphs.multi_dispatch import route_after_feedback


def _system_failure_result(
    *,
    failure_category: str = "",
    failure_detail: str = "",
    terminal_reason: str = "",
    error: str = "",
) -> SubTaskRuntimeState:
    return SubTaskRuntimeState.model_validate(
        {
            "subtask_id": "subtask_001",
            "status": "system_failure",
            "error": error,
            "summary": {
                "failure_category": failure_category,
                "failure_detail": failure_detail,
                "terminal_reason": terminal_reason,
            },
        }
    )


def test_monitor_uses_typed_failure_category_when_present() -> None:
    """Monitor must prefer pipeline-emitted failure_category over string matching."""
    state = {
        "execution": {
            "subtask_results": [
                _system_failure_result(
                    failure_category="rule_stale",
                    failure_detail="xpath_no_longer_matches",
                    # 故意写一段不含 rule_stale 关键词的自由文本，证明不走字符串匹配
                    terminal_reason="采集异常，站点可能改版",
                )
            ]
        },
        "control": {"active_strategy": {"name": "aggregate"}},
    }

    result = monitor_dispatch_node(state)

    assert result["control"]["active_strategy"]["name"] == "replan"
    failure = result["world"]["failure_records"][0]
    assert failure["category"] == "rule_stale"
    assert failure["detail"] == "xpath_no_longer_matches"
    assert failure["metadata"]["classification_reason"] == "pipeline_typed_signal"


def test_monitor_falls_back_to_string_matching_when_no_typed_category() -> None:
    """Legacy pipeline payloads without failure_category must keep working."""
    state = {
        "execution": {
            "subtask_results": [
                _system_failure_result(
                    terminal_reason="selector stale on detail page",
                )
            ]
        },
        "control": {"active_strategy": {"name": "aggregate"}},
    }

    result = monitor_dispatch_node(state)

    assert result["control"]["active_strategy"]["name"] == "replan"
    assert result["world"]["failure_records"][0]["category"] == "rule_stale"


def test_monitor_increments_replan_counter() -> None:
    state = {
        "execution": {
            "subtask_results": [
                _system_failure_result(failure_category="rule_stale", failure_detail="x")
            ]
        },
        "control": {
            "active_strategy": {"name": "replan", "replan_count": 1, "max_replans": 2},
            "recovery_policy": {"max_replans": 2},
        },
    }

    result = monitor_dispatch_node(state)

    active = result["control"]["active_strategy"]
    assert active["name"] == "replan"
    assert active["replan_count"] == 2
    assert active["max_replans"] == 2


def test_monitor_degrades_when_replan_budget_exhausted() -> None:
    state = {
        "execution": {
            "subtask_results": [
                _system_failure_result(failure_category="rule_stale", failure_detail="x")
            ]
        },
        "control": {
            "active_strategy": {"name": "replan", "replan_count": 2},
            "recovery_policy": {"max_replans": 2},
        },
    }

    result = monitor_dispatch_node(state)

    active = result["control"]["active_strategy"]
    assert active["name"] == "aggregate"
    assert active["reason"] == REPLAN_BUDGET_EXHAUSTED_REASON
    assert active["degraded_from"] == "replan"
    assert active["replan_count"] == 2
    assert route_after_feedback({"control": result["control"]}) == "aggregate"


def test_monitor_preserves_replan_count_on_non_replan_decision() -> None:
    state = {
        "execution": {
            "subtask_results": [
                SubTaskRuntimeState.model_validate(
                    {
                        "subtask_id": "subtask_002",
                        "status": "business_failure",
                        "summary": {
                            "failure_category": "fatal",
                            "failure_detail": "bad_selector",
                        },
                    }
                )
            ]
        },
        "control": {
            "active_strategy": {"name": "replan", "replan_count": 1, "max_replans": 2},
        },
    }

    result = monitor_dispatch_node(state)

    active = result["control"]["active_strategy"]
    # fatal 不触发 replan，走 aggregate；但 replan_count 保留以供审计
    assert active["name"] == "aggregate"
    assert active["replan_count"] == 1


def test_monitor_honors_request_params_recovery_policy_budget() -> None:
    state = {
        "execution": {
            "subtask_results": [
                _system_failure_result(failure_category="rule_stale", failure_detail="x")
            ]
        },
        "control": {"active_strategy": {"name": "replan", "replan_count": 1}},
        "conversation": {
            "normalized_params": {
                "recovery_policy": {"max_replans": 1},
            },
        },
    }

    result = monitor_dispatch_node(state)

    active = result["control"]["active_strategy"]
    assert active["name"] == "aggregate"
    assert active["reason"] == REPLAN_BUDGET_EXHAUSTED_REASON
    assert active["max_replans"] == 1
