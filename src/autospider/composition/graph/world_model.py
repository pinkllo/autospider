"""World-model contracts used by workflow decision helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from autospider.platform.shared_kernel.knowledge_contracts import normalize_profile_metadata
from autospider.platform.shared_kernel.knowledge_contracts import (
    DETAIL_FIELD_PROFILES_KEY,
    LIST_PAGE_PROFILE_KEY,
    build_list_profile_key,
    coerce_detail_field_profile,
    coerce_list_page_profile,
)

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
        metadata=normalize_profile_metadata(payload.get("metadata")),
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
        metadata=normalize_profile_metadata(metadata),
    )
    return WorldModel(
        request_params=dict(world_model.request_params),
        page_models=page_models,
        failure_records=tuple(world_model.failure_records),
        success_criteria=world_model.success_criteria,
    )


def merge_validated_list_profile(
    world_model: WorldModel,
    *,
    page_id: str,
    collection_config: Mapping[str, Any],
) -> WorldModel:
    config = dict(collection_config or {})
    if str(config.get("profile_validation_status") or "") != "validated":
        return world_model
    profile = coerce_list_page_profile(config)
    if not profile.common_detail_xpath:
        return world_model
    profile_key = str(config.get("profile_key") or profile.profile_key or "") or build_list_profile_key(
        page_state_signature=profile.page_state_signature,
        anchor_url=profile.anchor_url,
        variant_label=profile.variant_label,
        task_description=profile.task_description,
    )
    payload = dict(profile.to_payload())
    payload["profile_key"] = profile_key
    page = world_model.page_models.get(page_id) or PageModel(page_id=page_id)
    metadata = dict(page.metadata or {})
    profiles = dict(metadata.get(LIST_PAGE_PROFILE_KEY) or {})
    profiles[profile_key] = payload
    metadata[LIST_PAGE_PROFILE_KEY] = profiles
    return upsert_page_model(
        world_model,
        page_id=page_id,
        url=page.url or profile.list_url,
        page_type=page.page_type or "list_page",
        links=page.links,
        depth=page.depth,
        metadata=metadata,
    )


def resolve_list_profile_from_world(
    world_snapshot: Mapping[str, Any] | None,
    *,
    page_id: str = "",
    page_state_signature: str = "",
    anchor_url: str = "",
    variant_label: str = "",
    task_description: str = "",
) -> dict[str, Any]:
    candidates = resolve_list_profile_candidates_from_world(
        world_snapshot,
        page_id=page_id,
        page_state_signature=page_state_signature,
        anchor_url=anchor_url,
        variant_label=variant_label,
        task_description=task_description,
    )
    return dict(candidates[0]) if candidates else {}


def resolve_list_profile_candidates_from_world(
    world_snapshot: Mapping[str, Any] | None,
    *,
    page_id: str = "",
    page_state_signature: str = "",
    anchor_url: str = "",
    variant_label: str = "",
    task_description: str = "",
) -> list[dict[str, Any]]:
    world = dict(world_snapshot or {})
    raw_model = dict(world.get("world_model") or {})
    raw_pages = dict(raw_model.get("page_models") or {})
    page = dict(raw_pages.get(page_id) or {}) if page_id else {}
    metadata = normalize_profile_metadata(page.get("metadata"))
    profiles = metadata.get(LIST_PAGE_PROFILE_KEY)
    if not isinstance(profiles, Mapping):
        return []
    if "common_detail_xpath" in profiles:
        return [dict(profiles)]
    key = build_list_profile_key(
        page_state_signature=page_state_signature,
        anchor_url=anchor_url,
        variant_label=variant_label,
        task_description=task_description,
    )
    scored: list[tuple[int, dict[str, Any]]] = []
    for raw_candidate in profiles.values():
        if not isinstance(raw_candidate, Mapping):
            continue
        candidate = dict(raw_candidate)
        score = 0
        if str(candidate.get("profile_key") or "") == key:
            score += 8
        if page_state_signature and str(candidate.get("page_state_signature") or "") == page_state_signature:
            score += 4
        if anchor_url and str(candidate.get("anchor_url") or "") == anchor_url:
            score += 3
        if variant_label and str(candidate.get("variant_label") or "") == variant_label:
            score += 2
        if task_description and str(candidate.get("task_description") or "") == task_description:
            score += 2
        if str(candidate.get("common_detail_xpath") or "").strip():
            score += 1
        scored.append((score, candidate))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [dict(candidate) for _, candidate in scored]


def merge_detail_field_profiles(
    world_model: WorldModel,
    *,
    page_id: str,
    extraction_evidence: list[dict[str, Any]],
) -> WorldModel:
    page = world_model.page_models.get(page_id) or PageModel(page_id=page_id)
    metadata = dict(page.metadata or {})
    existing = [
        coerce_detail_field_profile(item).to_payload()
        for item in list(metadata.get(DETAIL_FIELD_PROFILES_KEY) or [])
        if isinstance(item, Mapping)
    ]
    index = {
        (
            str(item.get("detail_template_signature") or ""),
            str(item.get("field_signature") or ""),
        ): dict(item)
        for item in existing
    }
    for evidence in list(extraction_evidence or []):
        if not bool(evidence.get("success")):
            continue
        config = dict(evidence.get("extraction_config") or {})
        for raw_field in list(config.get("fields") or []):
            if not isinstance(raw_field, Mapping):
                continue
            profile = coerce_detail_field_profile(
                {
                    "field_name": raw_field.get("name"),
                    "xpath": raw_field.get("xpath"),
                    "xpath_fallbacks": raw_field.get("xpath_fallbacks"),
                    "extraction_source": raw_field.get("extraction_source"),
                    "validated": raw_field.get("xpath_validated"),
                    "detail_template_signature": raw_field.get("detail_template_signature"),
                    "field_signature": raw_field.get("field_signature"),
                }
            ).to_payload()
            if not str(profile.get("xpath") or "").strip():
                continue
            key = (
                str(profile.get("detail_template_signature") or ""),
                str(profile.get("field_signature") or ""),
            )
            if not all(key):
                continue
            index[key] = profile
    metadata[DETAIL_FIELD_PROFILES_KEY] = list(index.values())
    return upsert_page_model(
        world_model,
        page_id=page_id,
        url=page.url,
        page_type=page.page_type,
        links=page.links,
        depth=page.depth,
        metadata=metadata,
    )


def page_model_to_payload(page_model: PageModel) -> dict[str, Any]:
    return {
        "page_id": page_model.page_id,
        "url": page_model.url,
        "page_type": page_model.page_type,
        "links": page_model.links,
        "depth": page_model.depth,
        "metadata": normalize_profile_metadata(page_model.metadata),
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
