"""Extraction config and evidence helpers."""

from __future__ import annotations

from typing import Any

from .orchestration import PipelineRuntimeState


def _normalize_xpath_fallbacks(raw: Any) -> list[str]:
    return [str(item).strip() for item in list(raw or []) if str(item).strip()]


def _normalize_field_config(raw_field: Any) -> tuple[str, dict[str, Any]] | None:
    if not isinstance(raw_field, dict):
        return None
    name = str(raw_field.get("name") or "").strip()
    if not name:
        return None
    normalized = dict(raw_field)
    normalized["xpath_fallbacks"] = _normalize_xpath_fallbacks(raw_field.get("xpath_fallbacks"))
    return name, normalized


def _select_field_candidate(
    current: dict[str, Any],
    incoming: dict[str, Any],
) -> dict[str, Any]:
    current_xpath = str(current.get("xpath") or "").strip()
    incoming_xpath = str(incoming.get("xpath") or "").strip()
    current_validated = bool(current.get("xpath_validated"))
    incoming_validated = bool(incoming.get("xpath_validated"))
    if incoming_validated and (not current_validated or incoming_xpath):
        return dict(incoming)
    if incoming_xpath and not current_xpath:
        return dict(incoming)
    return dict(current)


def _build_fallback_xpaths(
    *,
    candidate_xpath: str,
    current: dict[str, Any],
    incoming: dict[str, Any],
) -> list[str]:
    current_xpath = str(current.get("xpath") or "").strip()
    incoming_xpath = str(incoming.get("xpath") or "").strip()
    fallback_pool = [
        *list(current.get("xpath_fallbacks") or []),
        *list(incoming.get("xpath_fallbacks") or []),
    ]
    if current_xpath and current_xpath != candidate_xpath:
        fallback_pool.append(current_xpath)
    if incoming_xpath and incoming_xpath != candidate_xpath:
        fallback_pool.append(incoming_xpath)
    seen = {candidate_xpath} if candidate_xpath else set()
    fallback_xpaths: list[str] = []
    for item in fallback_pool:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        fallback_xpaths.append(text)
    return fallback_xpaths[:5]


def merge_extraction_configs(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged_fields: dict[str, dict[str, Any]] = {}
    ordered_names: list[str] = []
    for config in (existing, incoming):
        for raw_field in list(dict(config or {}).get("fields") or []):
            normalized_field = _normalize_field_config(raw_field)
            if normalized_field is None:
                continue
            name, normalized = normalized_field
            if name not in ordered_names:
                ordered_names.append(name)
            current = merged_fields.get(name)
            if current is None:
                merged_fields[name] = normalized
                continue
            candidate = _select_field_candidate(current, normalized)
            candidate_xpath = str(candidate.get("xpath") or "").strip()
            candidate["xpath_fallbacks"] = _build_fallback_xpaths(
                candidate_xpath=candidate_xpath,
                current=current,
                incoming=normalized,
            )
            candidate["xpath_validated"] = bool(current.get("xpath_validated")) or bool(
                normalized.get("xpath_validated")
            )
            merged_fields[name] = candidate
    return {"fields": [merged_fields[name] for name in ordered_names if name in merged_fields]}


def record_extraction_evidence(
    state: PipelineRuntimeState | None,
    *,
    url: str,
    extraction_config: dict[str, Any],
    success: bool,
) -> None:
    if state is None:
        return
    state.extraction_evidence.append(
        {
            "url": url,
            "success": bool(success),
            "extraction_config": dict(extraction_config or {}),
        }
    )
    state.extraction_config = merge_extraction_configs(
        dict(state.extraction_config or {}),
        dict(extraction_config or {}),
    )


def build_error_reason(record: Any) -> str:
    errors = [field_result.error for field_result in record.fields if getattr(field_result, "error", "")]
    return "; ".join(errors) if errors else "extraction_failed"


def build_item_payload(record: Any) -> dict[str, Any]:
    item = {"url": record.url}
    for field_result in record.fields:
        item[field_result.field_name] = field_result.value
    return item
