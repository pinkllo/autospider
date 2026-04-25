from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from autospider.contexts.experience.domain.model import (
    SkillDocument,
    SkillFieldRule,
    SkillRuleData,
)
from autospider.contexts.experience.domain.policies import extract_domain
from autospider.contexts.experience.domain.ports import SkillRepository
from autospider.contexts.experience.application.skill_guide import (
    build_skill_guide,
    render_skill_guide_markdown,
)

_DEFAULT_STATUS = "validated"
_SUCCESS_COUNT_KEY = "success_count"
_TOTAL_URLS_KEY = "total_urls"
_DEFAULT_NAME_SUFFIX = " 站点采集"


@dataclass(frozen=True)
class SkillPromotionContext:
    anchor_url: str = ""
    page_state_signature: str = ""
    variant_label: str = ""
    context: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SkillSedimentationPayload:
    list_url: str
    task_description: str
    fields: list[dict[str, Any]]
    promotion_context: SkillPromotionContext = field(default_factory=SkillPromotionContext)
    collection_config: dict[str, Any] = field(default_factory=dict)
    extraction_config: dict[str, Any] = field(default_factory=dict)
    extraction_evidence: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    validation_failures: list[dict[str, Any]] = field(default_factory=list)
    subtask_names: list[str] = field(default_factory=list)
    plan_knowledge: str = ""
    status: str = _DEFAULT_STATUS


@dataclass(frozen=True)
class SkillCandidate:
    domain: str
    list_url: str
    task_description: str
    status: str
    summary: dict[str, Any] = field(default_factory=dict)
    collection_config: dict[str, Any] = field(default_factory=dict)
    extraction_config: dict[str, Any] = field(default_factory=dict)
    extraction_evidence: list[dict[str, Any]] = field(default_factory=list)
    validation_failures: list[dict[str, Any]] = field(default_factory=list)
    plan_knowledge: str = ""
    subtask_names: list[str] = field(default_factory=list)
    source: str = "single_run"
    page_state_signature: str = ""
    anchor_url: str = ""
    variant_label: str = ""
    context: dict[str, str] = field(default_factory=dict)


class SkillSedimenter:
    def __init__(self, repository: SkillRepository) -> None:
        self._repository = repository

    def sediment_from_pipeline_result(
        self,
        payload: SkillSedimentationPayload,
        *,
        overwrite_existing: bool = False,
    ) -> Path | None:
        del overwrite_existing
        candidate = _build_candidate(payload)
        if candidate is None:
            return None
        guide = build_skill_guide(candidate)
        path = self._repository.save_markdown(
            candidate.domain,
            render_skill_guide_markdown(guide),
            overwrite_existing=True,
        )
        return Path(path)


def _build_candidate(payload: SkillSedimentationPayload) -> SkillCandidate | None:
    summary = dict(payload.summary or {})
    success_count = int(summary.get(_SUCCESS_COUNT_KEY, 0) or 0)
    if success_count <= 0:
        return None
    domain = extract_domain(payload.list_url)
    if not domain:
        return None
    extraction_config = dict(payload.extraction_config or {})
    if not _has_usable_rules(extraction_config):
        return None
    return SkillCandidate(
        domain=domain,
        list_url=payload.list_url,
        task_description=payload.task_description,
        status=str(payload.status or _DEFAULT_STATUS),
        summary=summary,
        collection_config=dict(payload.collection_config or {}),
        extraction_config=extraction_config,
        extraction_evidence=list(payload.extraction_evidence or []),
        validation_failures=list(payload.validation_failures or []),
        plan_knowledge=str(payload.plan_knowledge or ""),
        subtask_names=list(payload.subtask_names or []),
        page_state_signature=str(payload.promotion_context.page_state_signature or ""),
        anchor_url=str(payload.promotion_context.anchor_url or ""),
        variant_label=str(payload.promotion_context.variant_label or ""),
        context=dict(payload.promotion_context.context or {}),
    )


def _build_document(candidate: SkillCandidate) -> SkillDocument:
    frontmatter = {
        "name": f"{candidate.domain}{_DEFAULT_NAME_SUFFIX}",
        "description": _build_description(candidate),
    }
    rules = SkillRuleData(
        domain=candidate.domain,
        name=str(frontmatter["name"]),
        description=str(frontmatter["description"]),
        list_url=candidate.list_url,
        task_description=candidate.task_description,
        status=str(candidate.status or _DEFAULT_STATUS),
        success_rate=_build_success_rate(candidate.summary),
        success_rate_text=_build_success_rate_text(candidate.summary),
        detail_xpath=_collection_detail_xpath(candidate.collection_config),
        pagination_xpath=str(candidate.collection_config.get("pagination_xpath") or ""),
        jump_input_selector=str(candidate.collection_config.get("jump_input_selector") or ""),
        jump_button_selector=str(candidate.collection_config.get("jump_button_selector") or ""),
        nav_steps=tuple(_build_nav_steps(candidate.collection_config)),
        subtask_names=tuple(candidate.subtask_names),
        fields=_build_field_rules(candidate),
    )
    return SkillDocument(
        frontmatter=frontmatter,
        title=f"# {candidate.domain} 采集指南",
        rules=rules,
        insights_markdown=str(candidate.plan_knowledge or ""),
    )


def _build_description(candidate: SkillCandidate) -> str:
    task_description = str(candidate.task_description or "").strip()
    if task_description:
        return task_description
    return f"{candidate.domain} 页面采集技能"


def _build_success_rate(summary: dict[str, Any]) -> float:
    success_count = int(summary.get(_SUCCESS_COUNT_KEY, 0) or 0)
    total_urls = int(summary.get(_TOTAL_URLS_KEY, 0) or 0)
    if total_urls <= 0:
        return 0.0
    return round(success_count / total_urls, 4)


def _build_success_rate_text(summary: dict[str, Any]) -> str:
    success_count = int(summary.get(_SUCCESS_COUNT_KEY, 0) or 0)
    total_urls = int(summary.get(_TOTAL_URLS_KEY, 0) or 0)
    if total_urls <= 0:
        return ""
    rate = _build_success_rate(summary)
    return f"{rate * 100:.0f}% ({success_count}/{total_urls})"


def _collection_detail_xpath(collection_config: dict[str, Any]) -> str:
    return str(
        collection_config.get("common_detail_xpath")
        or collection_config.get("detail_xpath")
        or ""
    ).strip()


def _has_usable_rules(extraction_config: dict[str, Any]) -> bool:
    for field_rule in list(extraction_config.get("fields") or []):
        xpath = str(field_rule.get("xpath") or "").strip()
        fixed_value = str(field_rule.get("fixed_value") or "").strip()
        if xpath or fixed_value:
            return True
    return False


def _build_nav_steps(collection_config: dict[str, Any]) -> list[dict[str, str]]:
    return [
        dict(step)
        for step in list(collection_config.get("nav_steps") or [])
        if isinstance(step, dict)
    ]


def _build_field_rules(candidate: SkillCandidate) -> dict[str, SkillFieldRule]:
    extraction_fields = {
        str(item.get("name") or "").strip(): dict(item)
        for item in list(candidate.extraction_config.get("fields") or [])
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    }
    failed_fields = _extract_failure_field_names(candidate.validation_failures)
    rules: dict[str, SkillFieldRule] = {}
    for raw_field in list(
        candidate.extraction_evidence
        or candidate.extraction_config.get("fields")
        or candidate.summary.get("fields")
        or candidate.collection_config.get("fields")
        or candidate.extraction_config.get("field_rules")
        or candidate.extraction_config.get("field_configs")
        or candidate.extraction_config.get("resolved_fields")
        or candidate.extraction_config.get("extracted_fields")
        or candidate.extraction_config.get("definitions")
        or candidate.extraction_config.get("items")
        or []
    ):
        if not isinstance(raw_field, dict):
            continue
        name = str(raw_field.get("name") or "").strip()
        if not name:
            continue
        config = extraction_fields.get(name, {})
        primary_xpath = str(config.get("xpath") or raw_field.get("xpath") or "").strip()
        fixed_value = str(config.get("fixed_value") or raw_field.get("fixed_value") or "").strip()
        rules[name] = SkillFieldRule(
            name=name,
            description=str(raw_field.get("description") or ""),
            data_type=str(raw_field.get("data_type") or "text"),
            extraction_source=str(
                config.get("extraction_source") or raw_field.get("extraction_source") or ""
            ),
            fixed_value=fixed_value,
            primary_xpath=primary_xpath,
            validated=bool(primary_xpath) and name not in failed_fields,
        )
    return rules


def _extract_failure_field_names(validation_failures: list[dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for item in list(validation_failures or []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("field_name") or item.get("field") or "").strip()
        if name:
            names.add(name)
    return names
