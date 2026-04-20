from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from autospider.legacy.pipeline.finalization import (
    PipelineFinalizationContext,
    _build_task_run_payload,
)
from autospider.legacy.pipeline.helpers import build_semantic_signature, build_strategy_payload


class _CapturedPayload:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _FakeTracker:
    async def mark_done(self, _status: str) -> None:
        return None


class _FakeSessions:
    async def stop(self) -> None:
        return None


def _make_context(**overrides) -> PipelineFinalizationContext:
    base = {
        "list_url": "https://example.com/list",
        "anchor_url": "https://example.com/list?page=1",
        "page_state_signature": "sig-001",
        "variant_label": "default",
        "task_description": "按学科分类采集专业列表",
        "semantic_signature": "semantic::category::001",
        "strategy_payload": {
            "group_by": "category",
            "per_group_target_count": 3,
            "total_target_count": None,
            "category_discovery_mode": "manual",
            "requested_categories": ["土木工程", "交通运输工程"],
            "category_examples": ["交通运输工程"],
        },
        "execution_brief": {"goal": "collect"},
        "fields": [SimpleNamespace(name="title")],
        "thread_id": "thread-001",
        "output_dir": "output/run-001",
        "output_path": Path("output/run-001"),
        "items_path": Path("output/run-001/items.jsonl"),
        "summary_path": Path("output/run-001/summary.json"),
        "staging_items_path": Path("output/run-001/items.staging.jsonl"),
        "staging_summary_path": Path("output/run-001/summary.staging.json"),
        "committed_records": {},
        "summary": {"execution_id": "exec-001", "mode": "crawl"},
        "runtime_state": SimpleNamespace(
            collection_config={"mode": "seed"},
            extraction_config={"strategy": "xpath"},
            validation_failures=[],
            extraction_evidence=[],
            error=None,
            terminal_reason="",
        ),
        "plan_knowledge": "plan knowledge",
        "task_plan": {},
        "plan_journal": [],
        "tracker": _FakeTracker(),
        "sessions": _FakeSessions(),
        "world_snapshot": {
            "request_params": {"list_url": "https://example.com/list"},
            "site_profile": {"host": "example.com", "supports_pagination": True},
        },
        "site_profile_snapshot": {"host": "example.com", "supports_pagination": True},
        "failure_patterns": [],
    }
    base.update(overrides)
    return PipelineFinalizationContext(**base)


def test_build_semantic_signature_is_stable_for_equivalent_grouping_requests() -> None:
    signature_a = build_semantic_signature(
        {
            "task_description": "按学科分类采集专业列表",
            "group_by": "category",
            "per_group_target_count": 3,
            "category_discovery_mode": "manual",
            "requested_categories": ["土木工程", "交通运输工程"],
            "category_examples": ["交通运输工程", "土木工程"],
        }
    )
    signature_b = build_semantic_signature(
        {
            "task_description": "把专业按分类各抓 3 条",
            "group_by": "category",
            "per_group_target_count": 3,
            "category_discovery_mode": "manual",
            "requested_categories": ["交通运输工程", "土木工程", "土木工程"],
            "category_examples": ["土木工程", "交通运输工程"],
        }
    )

    assert signature_a == signature_b


def test_build_semantic_signature_normalizes_explicit_legacy_strategy_payload() -> None:
    normalized_signature = build_semantic_signature(
        {
            "group_by": "category",
            "per_group_target_count": 3,
            "category_discovery_mode": "manual",
            "requested_categories": ["土木工程", "交通运输工程"],
            "category_examples": ["交通运输工程", "土木工程"],
            "fields": [{"name": "title"}, {"name": "published_at"}],
        }
    )
    legacy_signature = build_semantic_signature(
        {
            "task_description": "把专业按分类各抓 3 条",
            "strategy_payload": {
                "group_by": "CATEGORY",
                "per_group_target_count": "3",
                "total_target_count": "0",
                "category_discovery_mode": "MANUAL",
                "requested_categories": ["交通运输工程", "土木工程", "土木工程"],
                "category_examples": ["土木工程", "交通运输工程"],
                "field_names": ["published_at", "title", "title"],
            },
        }
    )

    assert normalized_signature == legacy_signature


def test_build_strategy_payload_fills_missing_field_names_from_surrounding_fields() -> None:
    payload = {
        "strategy_payload": {
            "group_by": "category",
            "per_group_target_count": 3,
            "category_discovery_mode": "manual",
            "requested_categories": ["土木工程", "交通运输工程"],
            "category_examples": ["交通运输工程", "土木工程"],
        },
        "fields": [{"name": "title"}, {"name": "published_at"}, {"name": "title"}],
    }

    strategy_payload = build_strategy_payload(payload)

    assert strategy_payload["field_names"] == ["published_at", "title"]


def test_build_semantic_signature_keeps_actual_field_set_when_explicit_payload_omits_field_names() -> (
    None
):
    payload_a = {
        "strategy_payload": {
            "group_by": "category",
            "per_group_target_count": 3,
            "category_discovery_mode": "manual",
            "requested_categories": ["土木工程", "交通运输工程"],
        },
        "fields": [{"name": "title"}, {"name": "published_at"}],
    }
    payload_b = {
        "strategy_payload": {
            "group_by": "category",
            "per_group_target_count": 3,
            "category_discovery_mode": "manual",
            "requested_categories": ["土木工程", "交通运输工程"],
        },
        "fields": [{"name": "title"}, {"name": "author"}],
    }

    assert build_semantic_signature(payload_a) != build_semantic_signature(payload_b)


def test_build_task_run_payload_includes_semantic_identity(monkeypatch) -> None:
    monkeypatch.setattr("autospider.platform.persistence.sql.orm.repositories.TaskRunPayload", _CapturedPayload)
    context = _make_context()

    payload = _build_task_run_payload(context, {})

    assert payload is not None
    assert payload.semantic_signature == "semantic::category::001"
    assert payload.strategy_payload["group_by"] == "category"
    assert payload.strategy_payload["requested_categories"] == ["土木工程", "交通运输工程"]
