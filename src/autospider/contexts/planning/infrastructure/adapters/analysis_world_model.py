from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

REUSE_STATUS = "reused"
UPDATE_STATUS = "updated"
FRESH_STATUS = "fresh"


def resolve_known_page_model(planner: object) -> dict[str, Any]:
    decision_context = _mapping_payload(getattr(planner, "decision_context", {}))
    page_model = _mapping_payload(decision_context.get("page_model"))
    if page_model:
        return page_model

    world_snapshot = _mapping_payload(getattr(planner, "world_snapshot", {}))
    world_model = _mapping_payload(world_snapshot.get("world_model"))
    page_models = _mapping_payload(world_model.get("page_models"))
    page_id = str(decision_context.get("page_id") or "").strip()
    if page_id and isinstance(page_models.get(page_id), Mapping):
        return dict(page_models[page_id])
    if len(page_models) == 1:
        return _mapping_payload(next(iter(page_models.values())))
    return {}


def format_known_page_model(page_model: Mapping[str, Any] | None) -> str:
    if not page_model:
        return "无"
    payload = _compact_page_model(page_model)
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def resolve_world_model_analysis(
    raw_result: Mapping[str, Any],
    known_page_model: Mapping[str, Any] | None,
) -> dict[str, Any]:
    status = str(raw_result.get("world_model_status") or "").strip().lower()
    if status == REUSE_STATUS:
        return _build_reused_analysis(known_page_model)
    if status == UPDATE_STATUS:
        update = _mapping_payload(raw_result.get("page_model_update"))
        if not update:
            raise ValueError("world_model_update_missing_page_model_update")
        return _merge_analysis(_build_reused_analysis(known_page_model), update, status=status)
    if status == FRESH_STATUS:
        fresh = dict(raw_result)
        fresh.pop("page_model_update", None)
        fresh["world_model_status"] = FRESH_STATUS
        return fresh
    return dict(raw_result)


def _mapping_payload(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _compact_page_model(page_model: Mapping[str, Any]) -> dict[str, Any]:
    metadata = _mapping_payload(page_model.get("metadata"))
    payload = {
        "page_id": page_model.get("page_id"),
        "url": page_model.get("url"),
        "page_type": page_model.get("page_type"),
        "links": page_model.get("links"),
        "depth": page_model.get("depth"),
        "metadata": {
            "name": metadata.get("name"),
            "observations": metadata.get("observations"),
            "task_description": metadata.get("task_description"),
            "context": metadata.get("context"),
            "analysis": metadata.get("analysis") or metadata.get("page_analysis"),
        },
    }
    return _drop_empty(payload)


def _drop_empty(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: cleaned
            for key, item in value.items()
            if (cleaned := _drop_empty(item)) not in (None, "", [], {})
        }
    if isinstance(value, list):
        return [cleaned for item in value if (cleaned := _drop_empty(item)) not in ({}, [])]
    return value


def _build_reused_analysis(known_page_model: Mapping[str, Any] | None) -> dict[str, Any]:
    page_model = _mapping_payload(known_page_model)
    if not page_model:
        raise ValueError("world_model_reuse_without_known_page_model")
    metadata = _mapping_payload(page_model.get("metadata"))
    analysis = _mapping_payload(metadata.get("analysis") or metadata.get("page_analysis"))
    resolved = dict(analysis) if analysis else _analysis_from_page_model(page_model, metadata)
    resolved["world_model_status"] = REUSE_STATUS
    return resolved


def _analysis_from_page_model(
    page_model: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "page_type": str(page_model.get("page_type") or ""),
        "name": str(metadata.get("name") or page_model.get("page_id") or ""),
        "task_description": str(metadata.get("task_description") or ""),
        "observations": str(metadata.get("observations") or ""),
        "category_controls_present": bool(metadata.get("category_controls_present") or False),
        "current_selected_category": str(metadata.get("current_selected_category") or ""),
        "supports_same_page_variant_switch": bool(
            metadata.get("supports_same_page_variant_switch") or False
        ),
        "category_candidates": list(metadata.get("category_candidates") or []),
        "subtasks": list(metadata.get("subtasks") or []),
    }


def _merge_analysis(
    base: Mapping[str, Any],
    update: Mapping[str, Any],
    *,
    status: str,
) -> dict[str, Any]:
    merged = dict(base)
    for key, value in dict(update).items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            nested = dict(merged[key])
            nested.update(dict(value))
            merged[key] = nested
        else:
            merged[key] = value
    merged["world_model_status"] = status
    return merged
