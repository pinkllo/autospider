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
    fields: list[SkillFieldRule] = Field(default_factory=list)
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
    existing_document: SkillDocument
    incoming_document: SkillDocument


class MergeSkillsResultDTO(BaseModel):
    merged_document: SkillDocumentDTO


class UpdateSkillStatsInput(BaseModel):
    document: SkillDocument
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
