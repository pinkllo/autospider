from __future__ import annotations

from pydantic import BaseModel, Field

from autospider.contexts.experience.domain.model import (
    SkillDocument,
    SkillFieldRule,
    SkillMetadata,
    SkillRuleData,
    SkillVariantRule,
)


class LookupSkillInput(BaseModel):
    url: str


class SkillMetadataDTO(BaseModel):
    name: str
    description: str
    path: str
    domain: str


class LookupSkillResultDTO(BaseModel):
    matches: list[SkillMetadataDTO] = Field(default_factory=list)


class SkillFieldRuleDTO(BaseModel):
    name: str
    description: str = ""
    data_type: str = "text"
    extraction_source: str = ""
    fixed_value: str = ""
    primary_xpath: str = ""
    fallback_xpaths: list[str] = Field(default_factory=list)
    validated: bool = False
    confidence: float = 0.0
    replace_primary: bool = False


class SkillVariantRuleDTO(BaseModel):
    label: str = ""
    page_state_signature: str = ""
    anchor_url: str = ""
    task_description: str = ""
    context: dict[str, str] = Field(default_factory=dict)
    success_rate: float = 0.0
    success_rate_text: str = ""
    detail_xpath: str = ""
    pagination_xpath: str = ""
    jump_input_selector: str = ""
    jump_button_selector: str = ""
    nav_steps: list[dict[str, str]] = Field(default_factory=list)
    fields: list[SkillFieldRuleDTO] = Field(default_factory=list)


class SkillRuleDataDTO(BaseModel):
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
    nav_steps: list[dict[str, str]] = Field(default_factory=list)
    subtask_names: list[str] = Field(default_factory=list)
    fields: list[SkillFieldRuleDTO] = Field(default_factory=list)
    variants: list[SkillVariantRuleDTO] = Field(default_factory=list)


class SkillDocumentDTO(BaseModel):
    frontmatter: dict[str, object] = Field(default_factory=dict)
    title: str
    rules: SkillRuleDataDTO
    insights_markdown: str = ""


class SedimentSkillInput(BaseModel):
    domain: str
    name: str
    description: str
    list_url: str
    task_description: str
    fields: list[SkillFieldRuleDTO] = Field(default_factory=list)
    status: str = "draft"
    success_count: int = 0
    total_count: int = 0
    frontmatter: dict[str, object] = Field(default_factory=dict)
    title: str | None = None
    insights_markdown: str = ""
    overwrite_existing: bool = False


class SedimentSkillResultDTO(BaseModel):
    path: str
    document: SkillDocumentDTO


class MergeSkillsInput(BaseModel):
    existing_document: SkillDocumentDTO
    incoming_document: SkillDocumentDTO


class MergeSkillsResultDTO(BaseModel):
    merged_document: SkillDocumentDTO


class UpdateSkillStatsInput(BaseModel):
    document: SkillDocumentDTO
    status: str
    success_rate: float
    success_rate_text: str = ""


class UpdateSkillStatsResultDTO(BaseModel):
    updated_document: SkillDocumentDTO


def to_skill_metadata_dto(metadata: SkillMetadata) -> SkillMetadataDTO:
    return SkillMetadataDTO(
        name=metadata.name,
        description=metadata.description,
        path=metadata.path,
        domain=metadata.domain,
    )


def to_skill_document_dto(document: SkillDocument) -> SkillDocumentDTO:
    return SkillDocumentDTO(
        frontmatter=dict(document.frontmatter),
        title=document.title,
        rules=to_skill_rule_data_dto(document.rules),
        insights_markdown=document.insights_markdown,
    )


def to_domain_skill_document(dto: SkillDocumentDTO) -> SkillDocument:
    return SkillDocument(
        frontmatter=dict(dto.frontmatter),
        title=dto.title,
        rules=to_domain_skill_rule_data(dto.rules),
        insights_markdown=dto.insights_markdown,
    )


def to_domain_field_map(fields: list[SkillFieldRuleDTO]) -> dict[str, SkillFieldRule]:
    mapped: dict[str, SkillFieldRule] = {}
    for field in fields:
        domain_field = to_domain_skill_field_rule(field)
        mapped[domain_field.name] = domain_field
    return mapped


def to_skill_rule_data_dto(rules: SkillRuleData) -> SkillRuleDataDTO:
    return SkillRuleDataDTO(
        domain=rules.domain,
        name=rules.name,
        description=rules.description,
        list_url=rules.list_url,
        task_description=rules.task_description,
        status=rules.status,
        success_rate=rules.success_rate,
        success_rate_text=rules.success_rate_text,
        detail_xpath=rules.detail_xpath,
        pagination_xpath=rules.pagination_xpath,
        jump_input_selector=rules.jump_input_selector,
        jump_button_selector=rules.jump_button_selector,
        nav_steps=list(rules.nav_steps),
        subtask_names=list(rules.subtask_names),
        fields=to_skill_field_rule_dtos(rules.fields),
        variants=[to_skill_variant_rule_dto(variant) for variant in rules.variants],
    )


def to_domain_skill_rule_data(dto: SkillRuleDataDTO) -> SkillRuleData:
    return SkillRuleData(
        domain=dto.domain,
        name=dto.name,
        description=dto.description,
        list_url=dto.list_url,
        task_description=dto.task_description,
        status=dto.status,
        success_rate=dto.success_rate,
        success_rate_text=dto.success_rate_text,
        detail_xpath=dto.detail_xpath,
        pagination_xpath=dto.pagination_xpath,
        jump_input_selector=dto.jump_input_selector,
        jump_button_selector=dto.jump_button_selector,
        nav_steps=tuple(dto.nav_steps),
        subtask_names=tuple(dto.subtask_names),
        fields=to_domain_field_map(dto.fields),
        variants=tuple(to_domain_skill_variant_rule(variant) for variant in dto.variants),
    )


def to_skill_field_rule_dtos(fields: dict[str, SkillFieldRule]) -> list[SkillFieldRuleDTO]:
    return [to_skill_field_rule_dto(field) for field in fields.values()]


def to_skill_field_rule_dto(field: SkillFieldRule) -> SkillFieldRuleDTO:
    return SkillFieldRuleDTO(
        name=field.name,
        description=field.description,
        data_type=field.data_type,
        extraction_source=field.extraction_source,
        fixed_value=field.fixed_value,
        primary_xpath=field.primary_xpath,
        fallback_xpaths=list(field.fallback_xpaths),
        validated=field.validated,
        confidence=field.confidence,
        replace_primary=field.replace_primary,
    )


def to_domain_skill_field_rule(dto: SkillFieldRuleDTO) -> SkillFieldRule:
    return SkillFieldRule(
        name=dto.name,
        description=dto.description,
        data_type=dto.data_type,
        extraction_source=dto.extraction_source,
        fixed_value=dto.fixed_value,
        primary_xpath=dto.primary_xpath,
        fallback_xpaths=tuple(dto.fallback_xpaths),
        validated=dto.validated,
        confidence=dto.confidence,
        replace_primary=dto.replace_primary,
    )


def to_skill_variant_rule_dto(variant: SkillVariantRule) -> SkillVariantRuleDTO:
    return SkillVariantRuleDTO(
        label=variant.label,
        page_state_signature=variant.page_state_signature,
        anchor_url=variant.anchor_url,
        task_description=variant.task_description,
        context=dict(variant.context),
        success_rate=variant.success_rate,
        success_rate_text=variant.success_rate_text,
        detail_xpath=variant.detail_xpath,
        pagination_xpath=variant.pagination_xpath,
        jump_input_selector=variant.jump_input_selector,
        jump_button_selector=variant.jump_button_selector,
        nav_steps=list(variant.nav_steps),
        fields=to_skill_field_rule_dtos(variant.fields),
    )


def to_domain_skill_variant_rule(dto: SkillVariantRuleDTO) -> SkillVariantRule:
    return SkillVariantRule(
        label=dto.label,
        page_state_signature=dto.page_state_signature,
        anchor_url=dto.anchor_url,
        task_description=dto.task_description,
        context=dict(dto.context),
        success_rate=dto.success_rate,
        success_rate_text=dto.success_rate_text,
        detail_xpath=dto.detail_xpath,
        pagination_xpath=dto.pagination_xpath,
        jump_input_selector=dto.jump_input_selector,
        jump_button_selector=dto.jump_button_selector,
        nav_steps=tuple(dto.nav_steps),
        fields=to_domain_field_map(dto.fields),
    )
