"""Field preparation helpers for subtask workers."""

from __future__ import annotations

from autospider.contexts.collection.domain.fields import FieldDefinition

_CATEGORY_FIELD_ALIASES = {
    "category",
    "categoryname",
    "projectcategory",
    "分类",
    "所属分类",
    "分类名称",
    "分类类别",
}
_CATEGORY_FIELD_MARKERS = (
    "所属分类",
    "分类名称",
    "分类类别",
    "categoryname",
    "projectcategory",
)


def _normalize_field_lookup_key(value: object | None) -> str:
    normalized = "".join(str(value or "").strip().lower().split())
    return normalized.replace("_", "")


def _build_field_lookup_keys(field: dict | None) -> list[str]:
    if not isinstance(field, dict):
        return []
    keys: list[str] = []
    for raw in (field.get("name"), field.get("description")):
        normalized = _normalize_field_lookup_key(raw)
        if normalized:
            keys.append(normalized)
    return keys


def _is_context_like_field(field: dict) -> bool:
    name = _normalize_field_lookup_key(field.get("name"))
    desc = _normalize_field_lookup_key(field.get("description"))
    if name in _CATEGORY_FIELD_ALIASES:
        return True
    return any(marker in desc for marker in _CATEGORY_FIELD_MARKERS)


def _resolve_fixed_field_value(subtask, field: dict | None = None) -> str:
    fixed_fields = dict(getattr(subtask, "fixed_fields", {}) or {})
    if not fixed_fields:
        return ""
    for lookup in _build_field_lookup_keys(field):
        for key, value in fixed_fields.items():
            if _normalize_field_lookup_key(key) != lookup:
                continue
            resolved = str(value or "").strip()
            if resolved:
                return resolved
    for key in ("category_name", "category", "所属分类", "分类"):
        resolved = str(fixed_fields.get(key) or "").strip()
        if resolved:
            return resolved
    return ""


def _resolve_scope_value(subtask) -> str:
    scope = dict(getattr(subtask, "scope", {}) or {})
    label = str(scope.get("label") or scope.get("name") or "").strip()
    if label:
        return label
    path = scope.get("path")
    if isinstance(path, (list, tuple)):
        segments = [str(item or "").strip() for item in path if str(item or "").strip()]
        if segments:
            return " > ".join(segments)
    return ""


def _resolve_context_value(subtask) -> str:
    context = dict(getattr(subtask, "context", {}) or {})
    for key in ("category_name", "category", "所属分类", "分类"):
        value = str(context.get(key) or "").strip()
        if value:
            return value
    return ""


def _resolve_explicit_context_value(subtask, field: dict | None = None) -> str:
    fixed_field_value = _resolve_fixed_field_value(subtask, field)
    if fixed_field_value:
        return fixed_field_value
    scope_value = _resolve_scope_value(subtask)
    if scope_value:
        return scope_value
    return _resolve_context_value(subtask)


def prepare_subtask_fields(subtask, raw_fields: list[dict]) -> list[FieldDefinition]:
    fields: list[FieldDefinition] = []
    source = subtask.fields if subtask.fields else raw_fields

    for field_config in source:
        if not isinstance(field_config, dict):
            continue
        try:
            extraction_source = field_config.get("extraction_source")
            fixed_value = field_config.get("fixed_value")
            if _is_context_like_field(field_config):
                subtask_context_value = _resolve_explicit_context_value(subtask, field_config)
                if subtask_context_value:
                    extraction_source = "subtask_context"
                    fixed_value = subtask_context_value

            fields.append(
                FieldDefinition(
                    name=field_config.get("name", ""),
                    description=field_config.get("description", ""),
                    required=field_config.get("required", True),
                    data_type=field_config.get("data_type", "text"),
                    example=field_config.get("example"),
                    extraction_source=extraction_source,
                    fixed_value=fixed_value,
                )
            )
        except Exception:
            continue

    return fields
