from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from autospider.legacy.domain.fields import FieldDefinition
from .models import ExtractionConfig, FieldRule
from .xpath_helpers import build_xpath_fallback_chain

_URL_FIELD_NAMES = {"detail_url", "url", "source_url", "page_url"}
_DIRECT_VALUE_SOURCES = {"constant", "subtask_context"}
FieldPayload = Mapping[str, Any]
FieldDefinitionInput = FieldDefinition | FieldPayload
FieldRuleInput = FieldRule | FieldPayload


def ensure_field_definition(field: FieldDefinitionInput) -> FieldDefinition:
    if isinstance(field, FieldDefinition):
        return field
    return FieldDefinition.from_mapping(field)


def ensure_field_rule(field: FieldRuleInput) -> FieldRule:
    if isinstance(field, FieldRule):
        return field
    return FieldRule.from_payload(field)


def ensure_field_rules(fields: Sequence[FieldRuleInput]) -> list[FieldRule]:
    return [ensure_field_rule(field) for field in fields]


def field_to_payload(field: FieldDefinition) -> dict[str, Any]:
    return field.to_payload()


def field_rule_to_payload(rule: FieldRule) -> dict[str, Any]:
    return rule.to_payload()


def field_rules_to_payload(rules: Sequence[FieldRule]) -> list[dict[str, Any]]:
    return [field_rule_to_payload(rule) for rule in rules]


def ensure_extraction_config(config: ExtractionConfig | Mapping[str, Any]) -> ExtractionConfig:
    if isinstance(config, ExtractionConfig):
        return config
    return ExtractionConfig.from_payload(config)


def build_rule_xpath_chain(rule: FieldRule) -> list[str]:
    fallback_xpaths = list(rule.xpath_fallbacks) if rule.xpath_fallbacks else None
    return build_xpath_fallback_chain(rule.xpath or "", fallback_xpaths)


def resolve_field_definition_value(
    field: FieldDefinition,
    *,
    url: str,
    infer_url_field_from_shape: bool = True,
) -> tuple[str | None, str | None]:
    source = str(field.extraction_source or "").strip().lower()
    fixed_value = field.fixed_value

    if source in _DIRECT_VALUE_SOURCES:
        if fixed_value is None:
            return None, None
        value = str(fixed_value).strip()
        return (value if value else None), source

    if source == "task_url":
        return url, "task_url"

    data_type = str(field.data_type or "").strip().lower()
    name = str(field.name or "").strip().lower()
    if infer_url_field_from_shape and data_type == "url" and name in _URL_FIELD_NAMES:
        return url, "task_url"
    return None, None


def resolve_field_rule_value(
    rule: FieldRule,
    *,
    url: str,
    infer_url_field_from_shape: bool = True,
) -> tuple[str | None, str | None]:
    return resolve_field_definition_value(
        rule.field,
        url=url,
        infer_url_field_from_shape=infer_url_field_from_shape,
    )


def resolve_non_xpath_field_value(
    field: FieldDefinition | FieldRuleInput,
    *,
    url: str,
    infer_url_field_from_shape: bool = True,
) -> tuple[str | None, str | None]:
    if isinstance(field, FieldRule):
        return resolve_field_rule_value(
            field,
            url=url,
            infer_url_field_from_shape=infer_url_field_from_shape,
        )
    return resolve_field_definition_value(
        ensure_field_definition(field),
        url=url,
        infer_url_field_from_shape=infer_url_field_from_shape,
    )
