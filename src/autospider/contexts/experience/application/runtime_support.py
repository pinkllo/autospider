from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any

from autospider.contexts.experience.domain.model import SkillMetadata


@dataclass(frozen=True)
class LoadedSkill:
    name: str
    description: str
    path: str
    domain: str
    content: str


def normalize_experience_context(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): normalize_experience_context(current)
            for key, current in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, list):
        return [normalize_experience_context(item) for item in value]
    if hasattr(value, "model_dump") and callable(value.model_dump):
        return normalize_experience_context(value.model_dump(mode="python"))
    if hasattr(value, "__dict__") and not isinstance(value, (str, bytes)):
        return normalize_object(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def normalize_object(value: Any) -> Any:
    try:
        return normalize_experience_context(asdict(value))
    except TypeError:
        attributes = {
            key: current
            for key, current in vars(value).items()
            if not key.startswith("_")
        }
        return normalize_experience_context(attributes)


def serialize_task_context(task_context: dict[str, Any] | None) -> str:
    normalized = normalize_experience_context(task_context or {})
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True)


def skill_to_dict(skill: SkillMetadata | LoadedSkill) -> dict[str, str]:
    return {
        "name": str(getattr(skill, "name", "") or ""),
        "description": str(getattr(skill, "description", "") or ""),
        "path": str(getattr(skill, "path", "") or ""),
        "domain": str(getattr(skill, "domain", "") or ""),
    }
