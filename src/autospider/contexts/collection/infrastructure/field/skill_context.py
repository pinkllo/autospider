from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from autospider.contexts.experience import SkillRuntime
from autospider.contexts.collection.domain.fields import FieldDefinition
from .field_config import ensure_field_definition, field_to_payload


def _serialize_selected_skills(selected: Sequence[Any]) -> list[dict[str, str]]:
    return [
        {
            "name": str(skill.name),
            "description": str(skill.description),
            "path": str(skill.path),
            "domain": str(skill.domain),
        }
        for skill in selected
    ]


def build_field_task_context(
    fields: Sequence[FieldDefinition],
) -> dict[str, list[dict[str, Any]]]:
    return {"fields": [field_to_payload(field) for field in fields]}


async def load_field_skill_context(
    skill_runtime: SkillRuntime,
    *,
    url: str,
    fields: Sequence[FieldDefinition],
    llm: Any = None,
    phase: str = "field_extractor",
    preselected_skills: Sequence[dict[str, str]] | None = None,
) -> tuple[list[dict[str, str]], str]:
    selected = await skill_runtime.get_or_select(
        phase=phase,
        url=url,
        task_context=build_field_task_context([ensure_field_definition(field) for field in fields]),
        llm=llm,
        preselected_skills=preselected_skills,
    )
    selected_skills = _serialize_selected_skills(selected)
    selected_skills_context = skill_runtime.format_selected_skills_context(
        skill_runtime.load_selected_bodies(selected)
    )
    return selected_skills, selected_skills_context


def apply_selected_skill_context(
    target: Any,
    *,
    selected_skills: list[dict[str, str]],
    selected_skills_context: str,
) -> None:
    if target is None:
        return
    if hasattr(target, "selected_skills"):
        target.selected_skills = list(selected_skills)
    if hasattr(target, "selected_skills_context"):
        target.selected_skills_context = selected_skills_context
