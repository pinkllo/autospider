"""World-model contracts used by workflow decision helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

DEFAULT_TARGET_URL_COUNT = 0


@dataclass(frozen=True, slots=True)
class PageModel:
    page_id: str
    url: str = ""
    page_type: str = ""
    links: int = 0
    depth: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FailureRecord:
    page_id: str = ""
    category: str = ""
    detail: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SuccessCriteria:
    target_url_count: int = DEFAULT_TARGET_URL_COUNT


@dataclass(frozen=True, slots=True)
class WorldModel:
    request_params: dict[str, Any] = field(default_factory=dict)
    page_models: dict[str, PageModel] = field(default_factory=dict)
    failure_records: tuple[FailureRecord, ...] = ()
    success_criteria: SuccessCriteria = field(default_factory=SuccessCriteria)


def _coerce_page_model(page_id: str, value: Any) -> PageModel:
    if isinstance(value, PageModel):
        return value
    payload = dict(value) if isinstance(value, Mapping) else {}
    return PageModel(
        page_id=str(payload.get("page_id") or page_id),
        url=str(payload.get("url") or ""),
        page_type=str(payload.get("page_type") or ""),
        links=int(payload.get("links", 0) or 0),
        depth=int(payload.get("depth", 0) or 0),
        metadata=dict(payload.get("metadata") or {}),
    )


def _coerce_failure_record(value: Any) -> FailureRecord:
    if isinstance(value, FailureRecord):
        return value
    payload = dict(value) if isinstance(value, Mapping) else {}
    return FailureRecord(
        page_id=str(payload.get("page_id") or ""),
        category=str(payload.get("category") or ""),
        detail=str(payload.get("detail") or ""),
        metadata=dict(payload.get("metadata") or {}),
    )


def _coerce_success_criteria(value: Any, request_params: Mapping[str, Any]) -> SuccessCriteria:
    if isinstance(value, SuccessCriteria):
        return value
    payload = dict(value) if isinstance(value, Mapping) else {}
    target_url_count = payload.get("target_url_count")
    if target_url_count is None:
        target_url_count = request_params.get("target_url_count", DEFAULT_TARGET_URL_COUNT)
    return SuccessCriteria(target_url_count=int(target_url_count or 0))


def build_initial_world_model(
    *,
    request_params: Mapping[str, Any] | None = None,
    page_models: Mapping[str, Any] | None = None,
    failure_records: list[Any] | tuple[Any, ...] | None = None,
    success_criteria: Mapping[str, Any] | SuccessCriteria | None = None,
) -> WorldModel:
    normalized_request = dict(request_params or {})
    normalized_pages = {
        str(page_id): _coerce_page_model(str(page_id), page_model)
        for page_id, page_model in dict(page_models or {}).items()
    }
    normalized_failures = tuple(
        _coerce_failure_record(item) for item in list(failure_records or [])
    )
    normalized_success = _coerce_success_criteria(success_criteria, normalized_request)
    return WorldModel(
        request_params=normalized_request,
        page_models=normalized_pages,
        failure_records=normalized_failures,
        success_criteria=normalized_success,
    )


def upsert_page_model(
    world_model: WorldModel,
    *,
    page_id: str,
    url: str = "",
    page_type: str = "",
    links: int = 0,
    depth: int = 0,
    metadata: Mapping[str, Any] | None = None,
) -> WorldModel:
    page_models = dict(world_model.page_models)
    page_models[page_id] = PageModel(
        page_id=page_id,
        url=str(url or ""),
        page_type=str(page_type or ""),
        links=int(links or 0),
        depth=int(depth or 0),
        metadata=dict(metadata or {}),
    )
    return WorldModel(
        request_params=dict(world_model.request_params),
        page_models=page_models,
        failure_records=tuple(world_model.failure_records),
        success_criteria=world_model.success_criteria,
    )


def page_model_to_payload(page_model: PageModel) -> dict[str, Any]:
    return {
        "page_id": page_model.page_id,
        "url": page_model.url,
        "page_type": page_model.page_type,
        "links": page_model.links,
        "depth": page_model.depth,
        "metadata": dict(page_model.metadata),
    }


def failure_record_to_payload(record: FailureRecord) -> dict[str, Any]:
    return {
        "page_id": record.page_id,
        "category": record.category,
        "detail": record.detail,
        "metadata": dict(record.metadata),
    }


def success_criteria_to_payload(success_criteria: SuccessCriteria) -> dict[str, Any]:
    return {"target_url_count": success_criteria.target_url_count}


def world_model_to_payload(world_model: WorldModel) -> dict[str, Any]:
    return {
        "request_params": dict(world_model.request_params),
        "page_models": {
            page_id: page_model_to_payload(page_model)
            for page_id, page_model in world_model.page_models.items()
        },
        "failure_records": [
            failure_record_to_payload(record) for record in world_model.failure_records
        ],
        "success_criteria": success_criteria_to_payload(world_model.success_criteria),
    }
