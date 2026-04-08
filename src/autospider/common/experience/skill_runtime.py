"""Skill runtime helpers for discovery, selection, and context loading."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any
from urllib.parse import urlparse

from langchain_core.messages import HumanMessage, SystemMessage

from ..config import config
from ..llm.streaming import ainvoke_with_stream
from ..llm.trace_logger import append_llm_trace
from ..logger import get_logger
from ..protocol import (
    extract_json_dict_from_llm_payload,
    extract_response_text_from_llm_payload,
    summarize_llm_payload,
)
from ..utils.paths import get_prompt_path
from ..utils.prompt_template import render_template
from .skill_store import SkillMetadata, SkillStore

logger = get_logger(__name__)

PROMPT_TEMPLATE_PATH = get_prompt_path("skill_selector.yaml")
_MAX_SELECTED_SKILLS = 3


@dataclass(frozen=True)
class LoadedSkill:
    """Loaded skill body plus frontmatter metadata."""

    name: str
    description: str
    path: str
    domain: str
    content: str


def _normalize_host(url: str) -> str:
    try:
        parsed = urlparse(str(url or ""))
        host = (parsed.netloc or parsed.path.split("/")[0] or "").strip().lower()
    except Exception:
        host = str(url or "").strip().lower()
    if not host:
        return ""
    if "@" in host:
        host = host.rsplit("@", 1)[-1]
    if ":" in host and not host.startswith("["):
        host = host.split(":", 1)[0]
    return host.rstrip(".")


def _normalize_task_context(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _normalize_task_context(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, list):
        return [_normalize_task_context(item) for item in value]
    if hasattr(value, "model_dump") and callable(value.model_dump):
        return _normalize_task_context(value.model_dump(mode="python"))
    if hasattr(value, "__dict__") and not isinstance(value, (str, bytes)):
        try:
            return _normalize_task_context(asdict(value))
        except Exception:
            pass
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _serialize_task_context(task_context: dict[str, Any] | None) -> str:
    normalized = _normalize_task_context(task_context or {})
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True)


def _skill_to_dict(skill: SkillMetadata | LoadedSkill) -> dict[str, str]:
    return {
        "name": str(getattr(skill, "name", "") or ""),
        "description": str(getattr(skill, "description", "") or ""),
        "path": str(getattr(skill, "path", "") or ""),
        "domain": str(getattr(skill, "domain", "") or ""),
    }


class SkillRuntime:
    """Discovery + selection + body loading runtime for site skills."""

    def __init__(self, store: SkillStore | None = None):
        self.store = store or SkillStore()
        self._selection_cache: dict[tuple[str, str, str], list[SkillMetadata]] = {}

    def discover_by_url(self, url: str) -> list[SkillMetadata]:
        return self.store.list_by_url(url)

    async def select_for_phase(
        self,
        *,
        phase: str,
        url: str,
        task_context: dict[str, Any] | None,
        available_skills: list[SkillMetadata],
        llm: Any,
    ) -> list[SkillMetadata]:
        skills = list(available_skills or [])
        if not skills or llm is None:
            return []

        system_prompt = render_template(
            PROMPT_TEMPLATE_PATH,
            section="select_skill_system_prompt",
            variables={"max_selected_skills": _MAX_SELECTED_SKILLS},
        )
        user_prompt = render_template(
            PROMPT_TEMPLATE_PATH,
            section="select_skill_user_prompt",
            variables={
                "phase": phase,
                "current_url": url,
                "task_context_json": _serialize_task_context(task_context),
                "available_skills": self._format_available_skills(skills),
                "max_selected_skills": _MAX_SELECTED_SKILLS,
            },
        )

        selected_indexes: list[int] = []
        raw_response = ""
        reasoning = ""
        payload: dict[str, Any] = {}
        response_summary: dict[str, Any] = {}
        try:
            response = await ainvoke_with_stream(
                llm,
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_prompt),
                ],
            )
            raw_response = extract_response_text_from_llm_payload(response)
            payload = extract_json_dict_from_llm_payload(response) or {}
            response_summary = summarize_llm_payload(response)
            reasoning = str(payload.get("reasoning") or "").strip()
            selected_indexes = self._parse_selected_indexes(
                payload.get("selected_indexes"),
                available_count=len(skills),
                reasoning=reasoning,
            )
        except Exception as exc:
            logger.debug("[SkillRuntime] skill selection failed for %s: %s", phase, exc)

        selected = [
            skills[index - 1]
            for index in selected_indexes
            if 1 <= index <= len(skills)
        ]
        selected = selected[:_MAX_SELECTED_SKILLS]

        append_llm_trace(
            component="skill_selector",
            payload={
                "model": getattr(llm, "model_name", None) or getattr(llm, "model", None) or config.llm.model,
                "input": {
                    "phase": phase,
                    "url": url,
                    "task_context": _normalize_task_context(task_context or {}),
                    "available_skills": [_skill_to_dict(skill) for skill in skills],
                    "system_prompt": system_prompt,
                    "user_prompt": user_prompt,
                },
                "output": {
                    "response_summary": response_summary,
                    "raw_response": raw_response,
                    "parsed_payload": payload,
                    "selected_indexes": selected_indexes,
                    "selected_skills": [_skill_to_dict(skill) for skill in selected],
                    "selected_skill_paths": [skill.path for skill in selected],
                    "reasoning": reasoning,
                },
            },
        )
        return selected

    def load_selected_bodies(self, selected_skills: list[SkillMetadata | dict[str, str]]) -> list[LoadedSkill]:
        loaded: list[LoadedSkill] = []
        for item in selected_skills or []:
            meta = self._coerce_metadata(item)
            if meta is None:
                continue
            if not self.store.is_llm_eligible_path(meta.path):
                continue
            content = self.store.load_by_path(meta.path)
            if not content:
                continue
            loaded.append(
                LoadedSkill(
                    name=meta.name,
                    description=meta.description,
                    path=meta.path,
                    domain=meta.domain,
                    content=content,
                )
            )
        return loaded

    def format_selected_skills_context(self, loaded_skills: list[LoadedSkill]) -> str:
        items = list(loaded_skills or [])
        if not items:
            return "当前未选择任何站点 skills。"

        lines = [
            "以下是已选中的站点 skills。它们只提供先验经验，不能替代当前页面观察；若与当前页面、截图或 DOM 冲突，以当前页面为准。",
        ]
        for index, skill in enumerate(items, start=1):
            lines.append(f"## Skill {index}")
            lines.append(f"- name: {skill.name}")
            lines.append(f"- description: {skill.description}")
            lines.append(f"- domain: {skill.domain}")
            lines.append(skill.content.strip())
        return "\n\n".join(lines)

    async def get_or_select(
        self,
        *,
        phase: str,
        url: str,
        task_context: dict[str, Any] | None,
        llm: Any,
        preselected_skills: list[SkillMetadata | dict[str, str]] | None = None,
    ) -> list[SkillMetadata]:
        host = _normalize_host(url)
        fingerprint = self._task_fingerprint(task_context)
        cache_key = (phase, host, fingerprint)
        if cache_key in self._selection_cache:
            return list(self._selection_cache[cache_key])

        available = self.discover_by_url(url)
        seeded = self._coerce_metadata_list(preselected_skills or [], host=host)
        if seeded:
            self._selection_cache[cache_key] = list(seeded)
            return list(seeded)
        selected = await self.select_for_phase(
            phase=phase,
            url=url,
            task_context=task_context,
            available_skills=available,
            llm=llm,
        )
        self._selection_cache[cache_key] = list(selected)
        return list(selected)

    def _task_fingerprint(self, task_context: dict[str, Any] | None) -> str:
        raw = _serialize_task_context(task_context)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def _format_available_skills(self, items: list[SkillMetadata]) -> str:
        if not items:
            return "无"
        payload = [
            {
                "index": index,
                "name": item.name,
                "description": item.description,
                "domain": item.domain,
            }
            for index, item in enumerate(items, start=1)
        ]
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _parse_selected_indexes(
        self,
        value: Any,
        *,
        available_count: int,
        reasoning: str = "",
    ) -> list[int]:
        if not isinstance(value, list):
            return []
        result: list[int] = []
        seen: set[int] = set()
        normalized_reasoning = reasoning.lower()
        for item in value:
            try:
                index = int(item)
            except (TypeError, ValueError):
                continue
            if index == 0 and available_count > 0:
                logger.warning(
                    "[SkillRuntime] skill selector returned 0-based index 0; auto-correcting to 1. reasoning=%s",
                    reasoning,
                )
                index = 1
            if index <= 0 or index > available_count or index in seen:
                continue
            seen.add(index)
            result.append(index)
            if len(result) >= _MAX_SELECTED_SKILLS:
                break
        return result

    def _coerce_metadata(self, item: SkillMetadata | dict[str, str]) -> SkillMetadata | None:
        if isinstance(item, SkillMetadata):
            return item
        if not isinstance(item, dict):
            return None
        name = str(item.get("name") or "").strip()
        description = str(item.get("description") or "").strip()
        path = str(item.get("path") or "").strip()
        domain = str(item.get("domain") or "").strip()
        if not name or not description or not path:
            return None
        return SkillMetadata(
            name=name,
            description=description,
            path=path,
            domain=domain,
        )

    def _coerce_metadata_list(
        self,
        items: list[SkillMetadata | dict[str, str]],
        *,
        host: str,
    ) -> list[SkillMetadata]:
        result: list[SkillMetadata] = []
        seen_paths: set[str] = set()
        for item in items:
            meta = self._coerce_metadata(item)
            if meta is None:
                continue
            if host and meta.domain and meta.domain != host:
                continue
            if not self.store.is_llm_eligible_path(meta.path):
                continue
            if meta.path in seen_paths:
                continue
            seen_paths.add(meta.path)
            result.append(meta)
        return result[:_MAX_SELECTED_SKILLS]
