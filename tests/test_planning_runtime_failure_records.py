"""Regression tests for failure history propagation across replans.

Covers the Phase-1 review finding that rebuilt runtime payloads dropped
``failure_records`` after a replan, so subsequent dispatch rounds lost the
same history that triggered the replan and repeated the failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autospider.crawler.planner.task_planner import build_planner_world_payload
from autospider.contexts.planning.domain import TaskPlan
from autospider.graph.nodes.capability_nodes import build_planning_runtime_payload


def _sample_plan() -> TaskPlan:
    return TaskPlan(
        plan_id="plan-replay",
        site_url="https://example.com",
        original_request="demo",
    )


def _sample_failure_records() -> list[dict]:
    return [
        {
            "category": "rule_stale",
            "detail": "xpath_no_longer_matches",
            "component": "pipeline",
            "metadata": {"subtask_id": "sub_001"},
        },
        {
            "category": "site_defense",
            "detail": "blocked_by_captcha",
            "component": "pipeline",
            "metadata": {"subtask_id": "sub_002"},
        },
    ]


def _key_view(records: list[dict]) -> list[tuple]:
    """Reduce failure records to the stable keys downstream consumers rely on.

    world_model normalization may add defaults (e.g. empty ``page_id``) so
    direct ``==`` is too strict — assert on category/detail/metadata instead.
    """
    return [
        (str(r.get("category") or ""), str(r.get("detail") or ""), dict(r.get("metadata") or {}))
        for r in records
    ]


def test_build_planner_world_payload_threads_failure_records() -> None:
    plan = _sample_plan()
    failures = _sample_failure_records()

    world = build_planner_world_payload(plan, request_params={}, failure_records=failures)

    # top-level list must be preserved verbatim (monitor / SubTaskWorker path)
    assert world["failure_records"] == failures
    # world_model payload should also reflect the injected failures so downstream
    # consumers (SubTaskWorker, monitor) can read a consistent view.
    model = world["world_model"]
    assert _key_view(list(model.get("failure_records") or [])) == _key_view(failures)


def test_build_planner_world_payload_defaults_to_empty_without_failures() -> None:
    plan = _sample_plan()

    world = build_planner_world_payload(plan, request_params={})

    assert world["failure_records"] == []


def test_build_planning_runtime_payload_propagates_failure_records_end_to_end() -> None:
    """Every downstream consumer path must observe the failure history.

    The regression before this fix: ``world_snapshot.failure_records`` was empty
    after a replan, so ``SubTaskWorker(... failure_records=params[...])``
    dispatched against a fresh context and kept retrying stale selectors.
    """
    plan = _sample_plan()
    failures = _sample_failure_records()

    payload = build_planning_runtime_payload(
        plan=plan,
        plan_knowledge="",
        request_params={},
        failure_records=failures,
    )

    request_params = payload["request_params"]
    world = payload["world"]

    # top-level request_params — the source SubTaskWorker actually reads from
    assert request_params["failure_records"] == failures
    # world snapshot baked into request_params mirrors the same list
    world_snapshot = request_params["world_snapshot"]
    assert world_snapshot["failure_records"] == failures
    # nested world_model payload (consumed by world_model_access helpers)
    assert _key_view(list(world["world_model"].get("failure_records") or [])) == _key_view(failures)
    # and the world returned as a top-level dict
    assert world["failure_records"] == failures


def test_build_planning_runtime_payload_without_failures_yields_empty_lists() -> None:
    plan = _sample_plan()

    payload = build_planning_runtime_payload(
        plan=plan,
        plan_knowledge="",
        request_params={},
    )

    assert payload["request_params"]["failure_records"] == []
    assert payload["world"]["failure_records"] == []
