"""Reusable knowledge contracts shared across runtime, config, and skill layers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import hashlib
import json
from typing import Any

LIST_PAGE_PROFILE_KEY = "list_page_profile"
DETAIL_FIELD_PROFILES_KEY = "detail_field_profiles"
VISUAL_DECISION_HINTS_KEY = "visual_decision_hints"

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off", ""}


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _clean_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _clean_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _clean_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    normalized = _clean_text(value).lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    return False


def build_list_profile_key(
    *,
    page_state_signature: str = "",
    anchor_url: str = "",
    variant_label: str = "",
    task_description: str = "",
) -> str:
    payload = {
        "anchor_url": _clean_text(anchor_url),
        "page_state_signature": _clean_text(page_state_signature),
        "task_description": " ".join(_clean_text(task_description).split()).lower(),
        "variant_label": _clean_text(variant_label),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def build_detail_template_signature(*, url: str = "", page_hint: str = "") -> str:
    payload = {
        "url": _clean_text(url).split("?", 1)[0],
        "page_hint": " ".join(_clean_text(page_hint).split()).lower(),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def build_field_semantic_signature(
    *,
    field_name: str = "",
    description: str = "",
    data_type: str = "",
    extraction_source: str = "",
) -> str:
    payload = {
        "data_type": _clean_text(data_type).lower(),
        "description": " ".join(_clean_text(description).split()).lower(),
        "extraction_source": _clean_text(extraction_source).lower(),
        "field_name": _clean_text(field_name).lower(),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _coerce_nav_steps(value: Any) -> tuple[dict[str, str], ...]:
    steps: list[dict[str, str]] = []
    for item in list(value or []):
        if not isinstance(item, Mapping):
            continue
        step = {
            _clean_text(key): _clean_text(raw_value)
            for key, raw_value in dict(item).items()
            if _clean_text(key)
        }
        if step:
            steps.append(step)
    return tuple(steps)


def _coerce_xpath_list(value: Any) -> tuple[str, ...]:
    values: list[str] = []
    for item in list(value or []):
        xpath = _clean_text(item)
        if xpath:
            values.append(xpath)
    return tuple(values)


@dataclass(frozen=True, slots=True)
class JumpWidgetProfile:
    input_xpath: str = ""
    button_xpath: str = ""

    @classmethod
    def from_mapping(cls, value: Any) -> "JumpWidgetProfile":
        if isinstance(value, JumpWidgetProfile):
            return value
        payload = dict(value) if isinstance(value, Mapping) else {}
        return cls(
            input_xpath=_clean_text(payload.get("input") or payload.get("input_xpath")),
            button_xpath=_clean_text(payload.get("button") or payload.get("button_xpath")),
        )

    def to_payload(self) -> dict[str, str] | None:
        payload: dict[str, str] = {}
        if self.input_xpath:
            payload["input"] = self.input_xpath
        if self.button_xpath:
            payload["button"] = self.button_xpath
        return payload or None


@dataclass(frozen=True, slots=True)
class ListPageProfile:
    profile_key: str = ""
    list_url: str = ""
    anchor_url: str = ""
    page_state_signature: str = ""
    variant_label: str = ""
    task_description: str = ""
    nav_steps: tuple[dict[str, str], ...] = ()
    common_detail_xpath: str = ""
    pagination_xpath: str = ""
    jump_widget_xpath: JumpWidgetProfile = field(default_factory=JumpWidgetProfile)
    validated_at: str = ""
    source: str = ""
    confidence: float = 0.0

    @classmethod
    def from_mapping(cls, value: Any) -> "ListPageProfile":
        if isinstance(value, ListPageProfile):
            return value
        payload = dict(value) if isinstance(value, Mapping) else {}
        jump_widget = payload.get("jump_widget_xpath")
        if not isinstance(jump_widget, Mapping):
            jump_widget = {
                "input": payload.get("jump_input_selector") or payload.get("jump_input_xpath"),
                "button": payload.get("jump_button_selector") or payload.get("jump_button_xpath"),
            }
        return cls(
            profile_key=_clean_text(payload.get("profile_key")),
            list_url=_clean_text(payload.get("list_url")),
            anchor_url=_clean_text(payload.get("anchor_url")),
            page_state_signature=_clean_text(payload.get("page_state_signature")),
            variant_label=_clean_text(payload.get("variant_label") or payload.get("label")),
            task_description=_clean_text(payload.get("task_description")),
            nav_steps=_coerce_nav_steps(payload.get("nav_steps")),
            common_detail_xpath=_clean_text(
                payload.get("common_detail_xpath") or payload.get("detail_xpath")
            ),
            pagination_xpath=_clean_text(payload.get("pagination_xpath")),
            jump_widget_xpath=JumpWidgetProfile.from_mapping(jump_widget),
            validated_at=_clean_text(payload.get("validated_at")),
            source=_clean_text(payload.get("source")),
            confidence=_clean_float(payload.get("confidence") or payload.get("success_rate")),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "profile_key": self.profile_key,
            "list_url": self.list_url,
            "anchor_url": self.anchor_url,
            "page_state_signature": self.page_state_signature,
            "variant_label": self.variant_label,
            "task_description": self.task_description,
            "nav_steps": [dict(step) for step in self.nav_steps],
            "common_detail_xpath": self.common_detail_xpath,
            "pagination_xpath": self.pagination_xpath,
            "jump_widget_xpath": self.jump_widget_xpath.to_payload(),
            "validated_at": self.validated_at,
            "source": self.source,
            "confidence": self.confidence,
        }


@dataclass(frozen=True, slots=True)
class DetailFieldProfile:
    domain: str = ""
    detail_template_signature: str = ""
    field_signature: str = ""
    field_name: str = ""
    xpath: str = ""
    xpath_fallbacks: tuple[str, ...] = ()
    extraction_source: str = ""
    validated: bool = False
    success_count: int = 0
    failure_count: int = 0

    @classmethod
    def from_mapping(cls, value: Any) -> "DetailFieldProfile":
        if isinstance(value, DetailFieldProfile):
            return value
        payload = dict(value) if isinstance(value, Mapping) else {}
        field_name = _clean_text(payload.get("field_name") or payload.get("name"))
        return cls(
            domain=_clean_text(payload.get("domain")),
            detail_template_signature=_clean_text(
                payload.get("detail_template_signature") or payload.get("template_signature")
            ),
            field_signature=_clean_text(payload.get("field_signature") or field_name),
            field_name=field_name,
            xpath=_clean_text(payload.get("xpath") or payload.get("primary_xpath")),
            xpath_fallbacks=_coerce_xpath_list(
                payload.get("xpath_fallbacks") or payload.get("fallback_xpaths")
            ),
            extraction_source=_clean_text(payload.get("extraction_source")),
            validated=_clean_bool(payload.get("validated")),
            success_count=_clean_int(payload.get("success_count")),
            failure_count=_clean_int(payload.get("failure_count")),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "detail_template_signature": self.detail_template_signature,
            "field_signature": self.field_signature,
            "field_name": self.field_name,
            "xpath": self.xpath,
            "xpath_fallbacks": list(self.xpath_fallbacks),
            "extraction_source": self.extraction_source,
            "validated": self.validated,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
        }


@dataclass(frozen=True, slots=True)
class VisualDecisionHint:
    page_state_signature: str = ""
    purpose: str = ""
    target_text: str = ""
    resolved_xpath: str = ""
    last_mark_text: str = ""
    confidence: float = 0.0
    ttl_scope: str = ""

    @classmethod
    def from_mapping(cls, value: Any) -> "VisualDecisionHint":
        if isinstance(value, VisualDecisionHint):
            return value
        payload = dict(value) if isinstance(value, Mapping) else {}
        return cls(
            page_state_signature=_clean_text(payload.get("page_state_signature")),
            purpose=_clean_text(payload.get("purpose")),
            target_text=_clean_text(payload.get("target_text") or payload.get("target")),
            resolved_xpath=_clean_text(payload.get("resolved_xpath") or payload.get("xpath")),
            last_mark_text=_clean_text(payload.get("last_mark_text") or payload.get("mark_text")),
            confidence=_clean_float(payload.get("confidence")),
            ttl_scope=_clean_text(payload.get("ttl_scope")),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "page_state_signature": self.page_state_signature,
            "purpose": self.purpose,
            "target_text": self.target_text,
            "resolved_xpath": self.resolved_xpath,
            "last_mark_text": self.last_mark_text,
            "confidence": self.confidence,
            "ttl_scope": self.ttl_scope,
        }


def coerce_list_page_profile(value: Any) -> ListPageProfile:
    return ListPageProfile.from_mapping(value)


def coerce_detail_field_profile(value: Any) -> DetailFieldProfile:
    return DetailFieldProfile.from_mapping(value)


def coerce_visual_decision_hint(value: Any) -> VisualDecisionHint:
    return VisualDecisionHint.from_mapping(value)


def _is_list_page_profile_map(value: Mapping[str, Any]) -> bool:
    payload = dict(value)
    keys = {_clean_text(key) for key in payload if _clean_text(key)}
    profile_keys = {
        "profile_key", "list_url", "anchor_url", "page_state_signature", "variant_label",
        "label", "task_description", "nav_steps", "common_detail_xpath", "detail_xpath",
        "pagination_xpath", "jump_widget_xpath", "jump_input_selector", "jump_input_xpath",
        "jump_button_selector", "jump_button_xpath", "validated_at", "source", "confidence",
        "success_rate",
    }
    return bool(keys) and not keys & profile_keys and all(
        isinstance(item, (Mapping, ListPageProfile)) for item in payload.values()
    )


def normalize_profile_metadata(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(metadata, Mapping):
        return {}
    normalized = dict(metadata)
    if LIST_PAGE_PROFILE_KEY in normalized:
        raw_profiles = normalized.get(LIST_PAGE_PROFILE_KEY)
        if isinstance(raw_profiles, Mapping) and _is_list_page_profile_map(raw_profiles):
            normalized[LIST_PAGE_PROFILE_KEY] = {
                _clean_text(key): coerce_list_page_profile(value).to_payload()
                for key, value in dict(raw_profiles).items()
                if _clean_text(key)
            }
        else:
            normalized[LIST_PAGE_PROFILE_KEY] = coerce_list_page_profile(raw_profiles).to_payload()
    if DETAIL_FIELD_PROFILES_KEY in normalized:
        normalized[DETAIL_FIELD_PROFILES_KEY] = [
            coerce_detail_field_profile(item).to_payload()
            for item in list(normalized.get(DETAIL_FIELD_PROFILES_KEY) or [])
            if isinstance(item, (Mapping, DetailFieldProfile))
        ]
    if VISUAL_DECISION_HINTS_KEY in normalized:
        normalized[VISUAL_DECISION_HINTS_KEY] = [
            coerce_visual_decision_hint(item).to_payload()
            for item in list(normalized.get(VISUAL_DECISION_HINTS_KEY) or [])
            if isinstance(item, (Mapping, VisualDecisionHint))
        ]
    return normalized
