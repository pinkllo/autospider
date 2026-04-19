from __future__ import annotations

from dataclasses import dataclass, field


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
