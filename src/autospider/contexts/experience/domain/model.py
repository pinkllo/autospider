from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from autospider.platform.shared_kernel.knowledge_contracts import (
    DetailFieldProfile,
    JumpWidgetProfile,
    ListPageProfile,
    coerce_detail_field_profile,
    coerce_list_page_profile,
)


@dataclass(frozen=True, slots=True)
class SkillMetadata:
    name: str
    description: str
    path: str
    domain: str


@dataclass(frozen=True, slots=True)
class SkillFieldRule:
    name: str
    description: str = ""
    data_type: str = "text"
    extraction_source: str = ""
    fixed_value: str = ""
    primary_xpath: str = ""
    fallback_xpaths: tuple[str, ...] = ()
    validated: bool = False
    confidence: float = 0.0
    replace_primary: bool = False

    def to_detail_field_profile(
        self,
        *,
        domain: str = "",
        detail_template_signature: str = "",
        field_signature: str = "",
    ) -> DetailFieldProfile:
        return DetailFieldProfile(
            domain=domain,
            detail_template_signature=detail_template_signature,
            field_signature=field_signature or self.name,
            field_name=self.name,
            xpath=self.primary_xpath,
            xpath_fallbacks=tuple(self.fallback_xpaths),
            extraction_source=self.extraction_source,
            validated=self.validated,
            success_count=1 if self.validated else 0,
            failure_count=0 if self.validated else 1,
        )

    @classmethod
    def from_detail_field_profile(cls, profile: DetailFieldProfile | Mapping[str, Any]) -> "SkillFieldRule":
        normalized = coerce_detail_field_profile(profile)
        return cls(
            name=normalized.field_name,
            extraction_source=normalized.extraction_source,
            primary_xpath=normalized.xpath,
            fallback_xpaths=tuple(normalized.xpath_fallbacks),
            validated=normalized.validated,
        )


@dataclass(frozen=True, slots=True)
class SkillVariantRule:
    label: str = ""
    page_state_signature: str = ""
    anchor_url: str = ""
    task_description: str = ""
    context: dict[str, str] = field(default_factory=dict)
    success_rate: float = 0.0
    success_rate_text: str = ""
    detail_xpath: str = ""
    pagination_xpath: str = ""
    jump_input_selector: str = ""
    jump_button_selector: str = ""
    nav_steps: tuple[dict[str, str], ...] = ()
    fields: dict[str, SkillFieldRule] = field(default_factory=dict)

    def to_list_page_profile(
        self,
        *,
        list_url: str = "",
        source: str = "experience_skill",
    ) -> ListPageProfile:
        return ListPageProfile(
            list_url=list_url,
            anchor_url=self.anchor_url,
            page_state_signature=self.page_state_signature,
            variant_label=self.label,
            task_description=self.task_description,
            nav_steps=_normalize_nav_steps(self.nav_steps),
            common_detail_xpath=self.detail_xpath,
            pagination_xpath=self.pagination_xpath,
            jump_widget_xpath=JumpWidgetProfile(
                input_xpath=self.jump_input_selector,
                button_xpath=self.jump_button_selector,
            ),
            source=source,
            confidence=self.success_rate,
        )

    @classmethod
    def from_list_page_profile(cls, profile: ListPageProfile | Mapping[str, Any]) -> "SkillVariantRule":
        normalized = coerce_list_page_profile(profile)
        jump_widget = normalized.jump_widget_xpath
        return cls(
            label=normalized.variant_label,
            page_state_signature=normalized.page_state_signature,
            anchor_url=normalized.anchor_url,
            task_description=normalized.task_description,
            success_rate=normalized.confidence,
            detail_xpath=normalized.common_detail_xpath,
            pagination_xpath=normalized.pagination_xpath,
            jump_input_selector=jump_widget.input_xpath,
            jump_button_selector=jump_widget.button_xpath,
            nav_steps=_normalize_nav_steps(normalized.nav_steps),
        )


@dataclass(frozen=True, slots=True)
class SkillRuleData:
    domain: str = ""
    name: str = ""
    description: str = ""
    list_url: str = ""
    task_description: str = ""
    status: str = ""
    success_rate: float = 0.0
    success_rate_text: str = ""
    detail_xpath: str = ""
    pagination_xpath: str = ""
    jump_input_selector: str = ""
    jump_button_selector: str = ""
    nav_steps: tuple[dict[str, str], ...] = ()
    subtask_names: tuple[str, ...] = ()
    fields: dict[str, SkillFieldRule] = field(default_factory=dict)
    variants: tuple[SkillVariantRule, ...] = ()

    def to_list_page_profile(self, *, source: str = "experience_skill") -> ListPageProfile:
        return ListPageProfile(
            list_url=self.list_url,
            task_description=self.task_description,
            nav_steps=_normalize_nav_steps(self.nav_steps),
            common_detail_xpath=self.detail_xpath,
            pagination_xpath=self.pagination_xpath,
            jump_widget_xpath=JumpWidgetProfile(
                input_xpath=self.jump_input_selector,
                button_xpath=self.jump_button_selector,
            ),
            source=source,
            confidence=self.success_rate,
        )

    @classmethod
    def from_list_page_profile(cls, profile: ListPageProfile | Mapping[str, Any]) -> "SkillRuleData":
        normalized = coerce_list_page_profile(profile)
        jump_widget = normalized.jump_widget_xpath
        return cls(
            list_url=normalized.list_url,
            task_description=normalized.task_description,
            detail_xpath=normalized.common_detail_xpath,
            pagination_xpath=normalized.pagination_xpath,
            jump_input_selector=jump_widget.input_xpath,
            jump_button_selector=jump_widget.button_xpath,
            nav_steps=_normalize_nav_steps(normalized.nav_steps),
        )

    def to_detail_field_profiles(
        self,
        *,
        detail_template_signature: str = "",
    ) -> tuple[DetailFieldProfile, ...]:
        return tuple(
            field_rule.to_detail_field_profile(
                domain=self.domain,
                detail_template_signature=detail_template_signature,
                field_signature=field_name,
            )
            for field_name, field_rule in self.fields.items()
        )


@dataclass(frozen=True, slots=True)
class SkillDocument:
    frontmatter: dict[str, object]
    title: str
    rules: SkillRuleData
    insights_markdown: str = ""


@dataclass(frozen=True, slots=True)
class SkillIndexEntry:
    domain: str
    path: str
    name: str
    status: str
    success_rate: float = 0.0


def _normalize_nav_steps(
    nav_steps: tuple[dict[str, str], ...] | tuple[Mapping[str, Any], ...],
) -> tuple[dict[str, str], ...]:
    return tuple(
        {
            str(key): str(value)
            for key, value in dict(step).items()
            if str(key).strip()
        }
        for step in nav_steps
        if isinstance(step, Mapping)
    )
