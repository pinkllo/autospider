from __future__ import annotations

from typing import Any

from autospider.common.storage.task_run_query_service import (
    TaskRunQueryService,
    build_task_lookup_key,
)


class _FakeCache:
    def __init__(self, cached: list[dict[str, Any]] | None = None) -> None:
        self.cached = cached
        self.get_calls: list[str] = []
        self.set_calls: list[tuple[str, list[dict[str, Any]], int | None]] = []

    def get(self, normalized_url: str) -> list[dict[str, Any]] | None:
        self.get_calls.append(normalized_url)
        return self.cached

    def set(self, normalized_url: str, data: list[dict[str, Any]], ttl: int | None = None) -> None:
        self.set_calls.append((normalized_url, data, ttl))


def test_build_task_lookup_key_includes_all_identity_dimensions() -> None:
    lookup_key = build_task_lookup_key(
        " https://www.example.com/jobs?page=2&category=python ",
        page_state_signature="  page-v1 ",
        anchor_url=" https://example.com/jobs#results ",
        variant_label=" primary ",
    )

    assert lookup_key == {
        "normalized_url": "example.com/jobs?category=python",
        "page_state_signature": "page-v1",
        "anchor_url": "https://example.com/jobs#results",
        "variant_label": "primary",
    }


def test_build_task_lookup_key_coerces_missing_dimensions_to_empty_strings() -> None:
    lookup_key = build_task_lookup_key("https://example.com/jobs")

    assert lookup_key == {
        "normalized_url": "example.com/jobs",
        "page_state_signature": "",
        "anchor_url": "",
        "variant_label": "",
    }


def test_find_by_url_keeps_url_only_lookup_behavior(monkeypatch: Any) -> None:
    service = TaskRunQueryService()
    fake_cache = _FakeCache()
    recorded: list[str] = []
    expected = [{"execution_id": "run-1"}]

    def fake_db_find(normalized_url: str) -> list[dict[str, Any]]:
        recorded.append(normalized_url)
        return expected

    monkeypatch.setattr(
        "autospider.common.storage.task_run_query_service._cache",
        fake_cache,
    )
    monkeypatch.setattr(service, "_db_find_by_url", fake_db_find)

    result = service.find_by_url("https://www.example.com/jobs?page=3")

    assert result == expected
    assert recorded == ["example.com/jobs"]
    assert fake_cache.get_calls == ["example.com/jobs"]
    assert fake_cache.set_calls == [("example.com/jobs", expected, None)]


def test_get_runtime_state_by_execution_id(monkeypatch: Any) -> None:
    service = TaskRunQueryService()
    expected = {
        "execution_id": "run-1",
        "status": "running",
        "runtime_state": {"stage": "resume_backfilled"},
    }
    recorded: list[str] = []

    runtime_lookup = getattr(service, "_runtime_store_get", None)
    assert callable(runtime_lookup), "TaskRunQueryService should expose runtime lookup hook"

    def fake_runtime_get(execution_id: str) -> dict[str, Any] | None:
        recorded.append(execution_id)
        return expected

    monkeypatch.setattr(service, "_runtime_store_get", fake_runtime_get)

    get_runtime_state = getattr(service, "get_runtime_state", None)
    assert callable(get_runtime_state), "TaskRunQueryService should expose get_runtime_state"

    result = get_runtime_state(" run-1 ")

    assert result == expected
    assert recorded == ["run-1"]


def test_get_runtime_state_returns_none_for_blank_execution_id(monkeypatch: Any) -> None:
    service = TaskRunQueryService()
    recorded: list[str] = []

    runtime_lookup = getattr(service, "_runtime_store_get", None)
    assert callable(runtime_lookup), "TaskRunQueryService should expose runtime lookup hook"

    def fake_runtime_get(execution_id: str) -> dict[str, Any] | None:
        recorded.append(execution_id)
        return {"execution_id": execution_id}

    monkeypatch.setattr(service, "_runtime_store_get", fake_runtime_get)

    get_runtime_state = getattr(service, "get_runtime_state", None)
    assert callable(get_runtime_state), "TaskRunQueryService should expose get_runtime_state"

    assert get_runtime_state("   ") is None
    assert recorded == []
