from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..domain.fields import FieldDefinition
from .xpath_helpers import build_xpath_fallback_chain

_URL_FIELD_NAMES = {"detail_url", "url", "source_url", "page_url"}
_DIRECT_VALUE_SOURCES = {"constant", "subtask_context"}


def get_field_value(field: FieldDefinition | Mapping[str, Any], key: str) -> Any:
    if isinstance(field, Mapping):
        return field.get(key)
    return getattr(field, key, None)


def field_to_payload(field: FieldDefinition | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(field, Mapping):
        return dict(field)
    return field.model_dump(mode="python")


def field_config_to_definition(field: Mapping[str, Any]) -> FieldDefinition:
    return FieldDefinition(
        name=str(field.get("name") or "").strip(),
        description=str(field.get("description") or "").strip(),
        required=bool(field.get("required", True)),
        data_type=str(field.get("data_type") or "text").strip().lower() or "text",
        example=(str(field.get("example")) if field.get("example") is not None else None),
        extraction_source=(
            str(field.get("extraction_source")).strip()
            if field.get("extraction_source") is not None
            else None
        ),
        fixed_value=(
            str(field.get("fixed_value")).strip() if field.get("fixed_value") is not None else None
        ),
    )


def build_field_xpath_chain(field: FieldDefinition | Mapping[str, Any]) -> list[str]:
    raw_fallbacks = get_field_value(field, "xpath_fallbacks")
    fallback_xpaths = raw_fallbacks if isinstance(raw_fallbacks, list) else None
    return build_xpath_fallback_chain(
        str(get_field_value(field, "xpath") or "").strip(),
        fallback_xpaths,
    )


def resolve_non_xpath_field_value(
    field: FieldDefinition | Mapping[str, Any],
    *,
    url: str,
    infer_url_field_from_shape: bool = True,
) -> tuple[str | None, str | None]:
    source = str(get_field_value(field, "extraction_source") or "").strip().lower()
    fixed_value = get_field_value(field, "fixed_value")

    if source in _DIRECT_VALUE_SOURCES:
        if fixed_value is None:
            return None, None
        value = str(fixed_value).strip()
        return (value if value else None), source

    if source == "task_url":
        return url, "task_url"

    data_type = str(get_field_value(field, "data_type") or "").strip().lower()
    name = str(get_field_value(field, "name") or "").strip().lower()
    if infer_url_field_from_shape and data_type == "url" and name in _URL_FIELD_NAMES:
        return url, "task_url"
    return None, None
