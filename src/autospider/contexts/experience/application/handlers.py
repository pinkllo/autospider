from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from autospider.contexts.experience.application.dto import (
    SedimentSkillInput,
    SedimentSkillResultDTO,
)
from autospider.contexts.experience.application.skill_promotion import (
    SkillPromotionContext,
    SkillSedimentationPayload,
    SkillSedimenter,
)
from autospider.contexts.experience.application.use_cases.sediment_skill import SedimentSkill
from autospider.contexts.experience.domain.model import SkillFieldRule
from autospider.platform.shared_kernel.result import ResultEnvelope

_PIPELINE_SUMMARY_FILENAME = "pipeline_summary.json"


class SedimentSkillFieldPayload(BaseModel):
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


class SedimentSkillPayload(BaseModel):
    domain: str
    name: str
    description: str
    list_url: str
    task_description: str
    fields: list[SedimentSkillFieldPayload] = Field(default_factory=list)
    status: str = "draft"
    success_count: int = 0
    total_count: int = 0
    frontmatter: dict[str, object] = Field(default_factory=dict)
    title: str | None = None
    insights_markdown: str = ""
    overwrite_existing: bool = False


class CollectionFinalizedPayload(BaseModel):
    run_id: str = ""
    plan_id: str = ""
    status: str = ""
    artifacts_dir: str


class ExperienceHandlers:
    def __init__(self, sediment_skill: SedimentSkill) -> None:
        self._sediment_skill = sediment_skill

    async def handle_sediment_skill(
        self,
        payload: SedimentSkillPayload,
    ) -> ResultEnvelope[SedimentSkillResultDTO]:
        command = SedimentSkillInput(
            domain=payload.domain,
            name=payload.name,
            description=payload.description,
            list_url=payload.list_url,
            task_description=payload.task_description,
            fields=[_to_field_rule(item) for item in payload.fields],
            status=payload.status,
            success_count=payload.success_count,
            total_count=payload.total_count,
            frontmatter=dict(payload.frontmatter),
            title=payload.title,
            insights_markdown=payload.insights_markdown,
            overwrite_existing=payload.overwrite_existing,
        )
        return await self._sediment_skill.run(command)


class CollectionFinalizedHandler:
    def __init__(self, sedimenter: SkillSedimenter) -> None:
        self._sedimenter = sedimenter

    def handle(self, payload: CollectionFinalizedPayload) -> Path | None:
        summary = _load_pipeline_summary(payload.artifacts_dir)
        return self._sedimenter.sediment_from_pipeline_result(_to_sedimentation_payload(summary))


def _to_field_rule(payload: SedimentSkillFieldPayload) -> SkillFieldRule:
    return SkillFieldRule(
        name=payload.name,
        description=payload.description,
        data_type=payload.data_type,
        extraction_source=payload.extraction_source,
        fixed_value=payload.fixed_value,
        primary_xpath=payload.primary_xpath,
        fallback_xpaths=list(payload.fallback_xpaths),
        validated=payload.validated,
        confidence=payload.confidence,
        replace_primary=payload.replace_primary,
    )


def _load_pipeline_summary(artifacts_dir: str) -> dict[str, Any]:
    summary_path = Path(artifacts_dir) / _PIPELINE_SUMMARY_FILENAME
    if not summary_path.exists():
        raise FileNotFoundError(f"pipeline summary not found: {summary_path}")
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"pipeline summary must be an object: {summary_path}")
    list_url = str(payload.get("list_url") or "").strip()
    task_description = str(payload.get("task_description") or "").strip()
    if not list_url or not task_description:
        raise ValueError(f"pipeline summary missing list_url/task_description: {summary_path}")
    return payload


def _to_sedimentation_payload(summary: dict[str, Any]) -> SkillSedimentationPayload:
    return SkillSedimentationPayload(
        list_url=str(summary.get("list_url") or ""),
        task_description=str(summary.get("task_description") or ""),
        fields=_coerce_fields(summary),
        promotion_context=SkillPromotionContext(
            anchor_url=str(summary.get("anchor_url") or ""),
            page_state_signature=str(summary.get("page_state_signature") or ""),
            variant_label=str(summary.get("variant_label") or ""),
            context=_stringify_context(summary.get("execution_brief")),
        ),
        collection_config=dict(summary.get("collection_config") or {}),
        extraction_config=dict(summary.get("extraction_config") or {}),
        extraction_evidence=list(summary.get("extraction_evidence") or []),
        summary=dict(summary),
        validation_failures=list(summary.get("validation_failures") or []),
        plan_knowledge=str(summary.get("plan_knowledge") or ""),
        status="validated",
    )


def _coerce_fields(summary: dict[str, Any]) -> list[dict[str, Any]]:
    fields = summary.get("fields")
    if isinstance(fields, list):
        return [dict(item) for item in fields if isinstance(item, dict)]
    extraction_fields = dict(summary.get("extraction_config") or {}).get("fields")
    if isinstance(extraction_fields, list):
        return [dict(item) for item in extraction_fields if isinstance(item, dict)]
    return []


def _stringify_context(raw_context: Any) -> dict[str, str]:
    if not isinstance(raw_context, dict):
        return {}
    normalized: dict[str, str] = {}
    for key, value in raw_context.items():
        name = str(key or "").strip()
        text = str(value or "").strip()
        if name and text:
            normalized[name] = text
    return normalized
