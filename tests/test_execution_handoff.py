from __future__ import annotations

import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autospider.legacy.graph.execution_handoff import (
    build_chat_execution_params,
    build_chat_review_payload,
)
from autospider.legacy.pipeline.helpers import build_semantic_signature, build_strategy_payload
from autospider.legacy.pipeline.types import ExecutionRequest


def test_build_chat_handoff_preserves_grouping_semantics() -> None:
    state = {
        "cli_args": {
            "output_dir": "output",
            "request": "按学科分类采集专业列表",
        },
        "conversation": {
            "selected_skills": [],
        },
    }
    task = {
        "intent": "collect",
        "list_url": "https://example.com/majors",
        "task_description": "按学科分类采集专业列表",
        "fields": [{"name": "title", "description": "专业名称", "required": True}],
        "group_by": "category",
        "per_group_target_count": 10,
        "total_target_count": 100,
        "category_discovery_mode": "auto",
        "requested_categories": [],
        "category_examples": ["交通运输工程"],
    }

    review_payload = build_chat_review_payload(state=state, task=task, dispatch_mode="multi")
    execution_params = build_chat_execution_params(state=state, task=task, dispatch_mode="multi")

    assert review_payload["clarified_task"]["group_by"] == "category"
    assert review_payload["clarified_task"]["per_group_target_count"] == 10
    assert review_payload["clarified_task"]["total_target_count"] == 100
    assert review_payload["clarified_task"]["category_discovery_mode"] == "auto"
    assert review_payload["clarified_task"]["requested_categories"] == []
    assert review_payload["clarified_task"]["category_examples"] == ["交通运输工程"]
    assert execution_params["group_by"] == "category"
    assert execution_params["per_group_target_count"] == 10
    assert execution_params["total_target_count"] == 100
    assert execution_params["category_discovery_mode"] == "auto"
    assert execution_params["requested_categories"] == []
    assert execution_params["category_examples"] == ["交通运输工程"]


def test_build_chat_handoff_prepopulates_semantic_identity_for_fresh_task() -> None:
    state = {
        "cli_args": {
            "output_dir": "output",
            "request": "按学科分类采集专业列表",
        },
        "conversation": {
            "selected_skills": [],
        },
    }
    task = {
        "intent": "collect",
        "list_url": "https://example.com/majors",
        "task_description": "按学科分类采集专业列表",
        "fields": [{"name": "title", "description": "专业名称", "required": True}],
        "group_by": "category",
        "per_group_target_count": 10,
        "total_target_count": 100,
        "category_discovery_mode": "auto",
        "requested_categories": [],
        "category_examples": ["交通运输工程"],
        "semantic_signature": "",
        "strategy_payload": {},
    }

    review_payload = build_chat_review_payload(state=state, task=task, dispatch_mode="multi")
    execution_params = build_chat_execution_params(state=state, task=task, dispatch_mode="multi")
    expected_strategy_payload = build_strategy_payload(task)
    expected_semantic_signature = build_semantic_signature(task)

    assert review_payload["clarified_task"]["strategy_payload"] == expected_strategy_payload
    assert review_payload["clarified_task"]["semantic_signature"] == expected_semantic_signature
    assert execution_params["strategy_payload"] == expected_strategy_payload
    assert execution_params["semantic_signature"] == expected_semantic_signature


def test_build_chat_handoff_reconciles_stale_explicit_semantic_signature() -> None:
    state = {
        "cli_args": {
            "output_dir": "output",
            "request": "按学科分类采集专业列表",
        },
        "conversation": {
            "selected_skills": [],
        },
    }
    task = {
        "intent": "collect",
        "list_url": "https://example.com/majors",
        "task_description": "按学科分类采集专业列表",
        "fields": [{"name": "title", "description": "专业名称", "required": True}],
        "group_by": "category",
        "per_group_target_count": 10,
        "total_target_count": 100,
        "category_discovery_mode": "auto",
        "requested_categories": [],
        "category_examples": ["交通运输工程"],
        "semantic_signature": "stale-semantic-signature",
        "strategy_payload": {},
    }

    execution_params = build_chat_execution_params(state=state, task=task, dispatch_mode="multi")
    expected_semantic_signature = build_semantic_signature(task)

    assert execution_params["semantic_signature"] == expected_semantic_signature


def test_execution_request_from_params_preserves_grouping_semantics() -> None:
    request = ExecutionRequest.from_params(
        {
            "list_url": "https://example.com/majors",
            "task_description": "按学科分类采集专业列表",
            "fields": [{"name": "title", "description": "专业名称", "required": True}],
            "group_by": "category",
            "per_group_target_count": 10,
            "total_target_count": 100,
            "category_discovery_mode": "auto",
            "requested_categories": [],
            "category_examples": ["交通运输工程"],
        },
        thread_id="thread-1",
    )

    assert request.group_by == "category"
    assert request.per_group_target_count == 10
    assert request.total_target_count == 100
    assert request.category_discovery_mode == "auto"
    assert request.requested_categories == []
    assert request.category_examples == ["交通运输工程"]


def test_execution_request_from_params_normalizes_invalid_grouping_inputs() -> None:
    request = ExecutionRequest.from_params(
        {
            "list_url": "https://example.com/majors",
            "task_description": "按学科分类采集专业列表",
            "fields": [{"name": "title", "description": "专业名称", "required": True}],
            "group_by": "category",
            "per_group_target_count": 0,
            "total_target_count": -5,
            "category_discovery_mode": "manual",
            "requested_categories": [],
            "category_examples": ["交通运输工程"],
        },
        thread_id="thread-1",
    )

    assert request.group_by == "category"
    assert request.per_group_target_count is None
    assert request.total_target_count is None
    assert request.category_discovery_mode == "auto"
    assert request.requested_categories == []
    assert request.category_examples == ["交通运输工程"]
