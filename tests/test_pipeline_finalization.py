from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from autospider.platform.persistence.redis.task_run_query_service import TaskRunQueryService
from autospider.composition.legacy.pipeline.finalization import (
    PipelineFinalizationContext,
    _build_task_run_payload,
)


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
        "task_description": "collect products",
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
            "page_models": {"entry": {"page_type": "list_page"}},
        },
        "site_profile_snapshot": {"host": "example.com", "supports_pagination": True},
        "failure_patterns": [{"pattern_id": "loop-detected", "trigger": "ABAB loop"}],
    }
    base.update(overrides)
    return PipelineFinalizationContext(**base)


def test_build_task_run_payload_carries_learning_snapshots(monkeypatch) -> None:
    monkeypatch.setattr(
        "autospider.platform.persistence.sql.orm.repositories.TaskRunPayload",
        _CapturedPayload,
    )
    context = _make_context()
    records = {
        "https://example.com/detail-1": {
            "url": "https://example.com/detail-1",
            "success": True,
            "item": {"title": "example"},
            "durability_state": "durable",
        }
    }

    payload = _build_task_run_payload(context, records)

    assert payload is not None
    assert payload.world_snapshot == context.world_snapshot
    assert payload.world_snapshot["site_profile"]["host"] == "example.com"
    assert payload.site_profile_snapshot["supports_pagination"] is True
    assert payload.failure_patterns[0]["pattern_id"] == "loop-detected"


def test_task_run_query_service_returns_latest_site_profile() -> None:
    service = TaskRunQueryService()
    service.find_by_url = lambda _url: (_ for _ in ()).throw(
        AssertionError("get_latest_site_profile should not reuse find_by_url")
    )
    service._db_list_run_snapshots_by_url = lambda _url: [
        {
            "execution_id": "exec-002",
            "site_profile_snapshot": {"host": "example.com", "from_execution": "exec-002"},
            "world_snapshot": {"site_profile": {"host": "fallback.example.com"}},
        },
        {
            "execution_id": "exec-001",
            "site_profile_snapshot": {"host": "older.example.com", "from_execution": "exec-001"},
            "world_snapshot": {"site_profile": {"host": "older.example.com"}},
        },
    ]

    profile = service.get_latest_site_profile("https://example.com/list")

    assert profile == {"host": "example.com", "from_execution": "exec-002"}
