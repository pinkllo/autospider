from __future__ import annotations

from dataclasses import replace

from autospider.contexts.experience.domain.model import (
    SkillDocument,
    SkillFieldRule,
    SkillRuleData,
)
from autospider.contexts.experience.domain.policies import (
    build_success_rate_text,
    clamp_success_rate,
    compute_success_rate,
    normalize_skill_status,
)

_MAX_FALLBACK_XPATHS = 5


class SkillDocumentService:
    def build_skill_document(
        self,
        *,
        domain: str,
        name: str,
        description: str,
        list_url: str,
        task_description: str,
        fields: dict[str, SkillFieldRule],
        status: str = "draft",
        success_count: int = 0,
        total_count: int = 0,
        frontmatter: dict[str, object] | None = None,
        title: str | None = None,
        insights_markdown: str = "",
    ) -> SkillDocument:
        normalized_status = normalize_skill_status(status)
        success_rate = compute_success_rate(
            success_count=success_count,
            total_count=total_count,
        )
        success_rate_text = build_success_rate_text(
            success_count=success_count,
            total_count=total_count,
        )
        merged_frontmatter = dict(frontmatter or {})
        merged_frontmatter["name"] = name
        merged_frontmatter["description"] = description
        rules = SkillRuleData(
            domain=domain,
            name=name,
            description=description,
            list_url=list_url,
            task_description=task_description,
            status=normalized_status,
            success_rate=success_rate,
            success_rate_text=success_rate_text,
            fields=dict(fields),
        )
        return SkillDocument(
            frontmatter=merged_frontmatter,
            title=title or f"# {domain} 采集指南",
            rules=rules,
            insights_markdown=insights_markdown,
        )

    def merge_skill_documents(
        self,
        *,
        existing: SkillDocument,
        incoming: SkillDocument,
    ) -> SkillDocument:
        merged_fields = self._merge_fields(existing.rules.fields, incoming.rules.fields)
        merged_rules = SkillRuleData(
            domain=incoming.rules.domain or existing.rules.domain,
            name=incoming.rules.name or existing.rules.name,
            description=incoming.rules.description or existing.rules.description,
            list_url=incoming.rules.list_url or existing.rules.list_url,
            task_description=incoming.rules.task_description or existing.rules.task_description,
            status=normalize_skill_status(incoming.rules.status or existing.rules.status),
            success_rate=max(existing.rules.success_rate, incoming.rules.success_rate),
            success_rate_text=incoming.rules.success_rate_text or existing.rules.success_rate_text,
            detail_xpath=incoming.rules.detail_xpath or existing.rules.detail_xpath,
            pagination_xpath=incoming.rules.pagination_xpath or existing.rules.pagination_xpath,
            jump_input_selector=incoming.rules.jump_input_selector
            or existing.rules.jump_input_selector,
            jump_button_selector=incoming.rules.jump_button_selector
            or existing.rules.jump_button_selector,
            nav_steps=incoming.rules.nav_steps or existing.rules.nav_steps,
            subtask_names=incoming.rules.subtask_names or existing.rules.subtask_names,
            fields=merged_fields,
            variants=incoming.rules.variants or existing.rules.variants,
        )
        merged_frontmatter = dict(existing.frontmatter or incoming.frontmatter)
        merged_title = incoming.title or existing.title
        merged_insights = incoming.insights_markdown or existing.insights_markdown
        return SkillDocument(
            frontmatter=merged_frontmatter,
            title=merged_title,
            rules=merged_rules,
            insights_markdown=merged_insights,
        )

    def update_skill_stats(
        self,
        *,
        document: SkillDocument,
        status: str,
        success_rate: float,
        success_rate_text: str = "",
    ) -> SkillDocument:
        normalized_status = normalize_skill_status(status)
        normalized_rate = clamp_success_rate(success_rate)
        normalized_text = success_rate_text.strip()
        if not normalized_text:
            normalized_text = f"{normalized_rate * 100:.0f}%"
        updated_rules = replace(
            document.rules,
            status=normalized_status,
            success_rate=normalized_rate,
            success_rate_text=normalized_text,
        )
        return replace(document, rules=updated_rules)

    def _merge_fields(
        self,
        existing: dict[str, SkillFieldRule],
        incoming: dict[str, SkillFieldRule],
    ) -> dict[str, SkillFieldRule]:
        merged: dict[str, SkillFieldRule] = dict(existing)
        for field_name, incoming_rule in incoming.items():
            current_rule = merged.get(field_name)
            if current_rule is None:
                merged[field_name] = incoming_rule
                continue
            merged[field_name] = self._merge_single_field(current_rule, incoming_rule)
        return merged

    def _merge_single_field(
        self,
        existing: SkillFieldRule,
        incoming: SkillFieldRule,
    ) -> SkillFieldRule:
        if existing.validated and not incoming.validated and existing.primary_xpath:
            fallback_values = self._dedupe_xpaths(
                values=(
                    incoming.primary_xpath,
                    *incoming.fallback_xpaths,
                    *existing.fallback_xpaths,
                ),
                exclude={existing.primary_xpath},
            )
            return replace(
                existing,
                fallback_xpaths=fallback_values,
                confidence=max(existing.confidence, incoming.confidence),
            )
        fallback_values = self._dedupe_xpaths(
            values=(existing.primary_xpath, *incoming.fallback_xpaths, *existing.fallback_xpaths),
            exclude={incoming.primary_xpath},
        )
        return SkillFieldRule(
            name=incoming.name,
            description=incoming.description or existing.description,
            data_type=incoming.data_type or existing.data_type,
            extraction_source=incoming.extraction_source or existing.extraction_source,
            fixed_value=incoming.fixed_value or existing.fixed_value,
            primary_xpath=incoming.primary_xpath or existing.primary_xpath,
            fallback_xpaths=fallback_values,
            validated=existing.validated or incoming.validated,
            confidence=max(existing.confidence, incoming.confidence),
            replace_primary=incoming.replace_primary or existing.replace_primary,
        )

    def _dedupe_xpaths(
        self,
        *,
        values: tuple[str, ...],
        exclude: set[str] | None = None,
    ) -> tuple[str, ...]:
        seen = {value for value in (exclude or set()) if value}
        unique: list[str] = []
        for raw in values:
            value = str(raw or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            unique.append(value)
            if len(unique) >= _MAX_FALLBACK_XPATHS:
                break
        return tuple(unique)
