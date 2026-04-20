from __future__ import annotations

import hashlib
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from autospider.platform.config.runtime import config
from autospider.platform.llm.streaming import ainvoke_with_stream
from autospider.platform.llm.trace_logger import append_llm_trace
from autospider.platform.observability.logger import get_logger
from autospider.legacy.common.protocol import (
    extract_json_dict_from_llm_payload,
    extract_response_text_from_llm_payload,
    summarize_llm_payload,
)
from autospider.platform.shared_kernel.utils.paths import get_prompt_path
from autospider.platform.shared_kernel.utils.prompt_template import render_template
from autospider.contexts.experience.application.runtime_support import (
    LoadedSkill,
    serialize_task_context,
    skill_to_dict,
)
from autospider.contexts.experience.domain.policies import extract_domain
from autospider.contexts.experience.domain.ports import SkillRepository

logger = get_logger(__name__)

PROMPT_TEMPLATE_PATH = get_prompt_path("skill_selector.yaml")
_MAX_SELECTED_SKILLS = 3


class SkillRuntime:
    def __init__(self, repository: SkillRepository) -> None:
        self._repository = repository
        self._selection_cache: dict[tuple[str, str, str], list[Any]] = {}

    def discover_by_url(self, url: str) -> list[Any]:
        return self._repository.list_by_url(url)

    async def select_for_phase(
        self,
        *,
        phase: str,
        url: str,
        task_context: dict[str, Any] | None,
        available_skills: list[Any],
        llm: Any,
    ) -> list[Any]:
        skills = list(available_skills or [])
        if not skills or llm is None:
            return []
        prompts = _build_selector_prompts(
            phase=phase, url=url, task_context=task_context, skills=skills
        )
        response_payload = await _invoke_selector(llm=llm, prompts=prompts)
        selected = _select_skill_indexes(
            skills=skills,
            payload=response_payload["payload"],
            reasoning=response_payload["reasoning"],
        )
        _append_trace(
            llm=llm,
            phase=phase,
            url=url,
            task_context=task_context,
            skills=skills,
            prompts=prompts,
            response_payload=response_payload,
            selected=selected,
        )
        return selected

    def load_selected_bodies(self, selected_skills: list[Any]) -> list[LoadedSkill]:
        loaded: list[LoadedSkill] = []
        for meta in list(selected_skills or []):
            path = str(getattr(meta, "path", "") or "").strip()
            if not path or not self._repository.is_llm_eligible_path(path):
                continue
            content = self._repository.load_by_path(path)
            if not content:
                continue
            loaded.append(
                LoadedSkill(
                    name=str(getattr(meta, "name", "") or ""),
                    description=str(getattr(meta, "description", "") or ""),
                    path=path,
                    domain=str(getattr(meta, "domain", "") or ""),
                    content=content,
                )
            )
        return loaded

    def format_selected_skills_context(self, loaded_skills: list[LoadedSkill]) -> str:
        if not loaded_skills:
            return "当前未选择任何站点 skills。"
        lines = [
            "以下是已选中的站点 skills。它们只提供先验经验，不能替代当前页面观察；若与当前页面、截图或 DOM 冲突，以当前页面为准。",
        ]
        for index, skill in enumerate(loaded_skills, start=1):
            lines.extend(
                [
                    f"## Skill {index}",
                    f"- name: {skill.name}",
                    f"- description: {skill.description}",
                    f"- domain: {skill.domain}",
                    skill.content.strip(),
                ]
            )
        return "\n\n".join(lines)

    async def get_or_select(
        self,
        *,
        phase: str,
        url: str,
        task_context: dict[str, Any] | None,
        llm: Any,
        preselected_skills: list[dict[str, str]] | None = None,
    ) -> list[Any]:
        host = extract_domain(url)
        cache_key = (phase, host, _task_fingerprint(task_context))
        if cache_key in self._selection_cache:
            return list(self._selection_cache[cache_key])
        seeded = _coerce_metadata_list(self._repository, preselected_skills or [], host=host)
        if seeded:
            self._selection_cache[cache_key] = list(seeded)
            return list(seeded)
        selected = await self.select_for_phase(
            phase=phase,
            url=url,
            task_context=task_context,
            available_skills=self.discover_by_url(url),
            llm=llm,
        )
        self._selection_cache[cache_key] = list(selected)
        return list(selected)


def _task_fingerprint(task_context: dict[str, Any] | None) -> str:
    raw = serialize_task_context(task_context)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _build_selector_prompts(
    *,
    phase: str,
    url: str,
    task_context: dict[str, Any] | None,
    skills: list[Any],
) -> dict[str, str]:
    return {
        "system_prompt": render_template(
            PROMPT_TEMPLATE_PATH,
            section="select_skill_system_prompt",
            variables={"max_selected_skills": _MAX_SELECTED_SKILLS},
        ),
        "user_prompt": render_template(
            PROMPT_TEMPLATE_PATH,
            section="select_skill_user_prompt",
            variables={
                "phase": phase,
                "current_url": url,
                "task_context_json": serialize_task_context(task_context),
                "available_skills": _format_available_skills(skills),
                "max_selected_skills": _MAX_SELECTED_SKILLS,
            },
        ),
    }


async def _invoke_selector(*, llm: Any, prompts: dict[str, str]) -> dict[str, Any]:
    response = await ainvoke_with_stream(
        llm,
        [
            SystemMessage(content=prompts["system_prompt"]),
            HumanMessage(content=prompts["user_prompt"]),
        ],
    )
    payload = extract_json_dict_from_llm_payload(response) or {}
    return {
        "payload": payload,
        "raw_response": extract_response_text_from_llm_payload(response),
        "response_summary": summarize_llm_payload(response),
        "reasoning": str(payload.get("reasoning") or "").strip(),
    }


def _select_skill_indexes(
    *, skills: list[Any], payload: dict[str, Any], reasoning: str
) -> list[Any]:
    indexes = _parse_selected_indexes(
        payload.get("selected_indexes"),
        available_count=len(skills),
        reasoning=reasoning,
    )
    return [skills[index - 1] for index in indexes if 1 <= index <= len(skills)]


def _append_trace(
    *,
    llm: Any,
    phase: str,
    url: str,
    task_context: dict[str, Any] | None,
    skills: list[Any],
    prompts: dict[str, str],
    response_payload: dict[str, Any],
    selected: list[Any],
) -> None:
    append_llm_trace(
        component="skill_selector",
        payload={
            "model": getattr(llm, "model_name", None)
            or getattr(llm, "model", None)
            or config.llm.model,
            "input": {
                "phase": phase,
                "url": url,
                "task_context": task_context or {},
                "available_skills": [skill_to_dict(skill) for skill in skills],
                "system_prompt": prompts["system_prompt"],
                "user_prompt": prompts["user_prompt"],
            },
            "output": {
                "response_summary": response_payload["response_summary"],
                "raw_response": response_payload["raw_response"],
                "parsed_payload": response_payload["payload"],
                "selected_skills": [skill_to_dict(skill) for skill in selected],
                "selected_skill_paths": [
                    str(getattr(skill, "path", "") or "") for skill in selected
                ],
                "reasoning": response_payload["reasoning"],
            },
        },
    )


def _format_available_skills(items: list[Any]) -> str:
    if not items:
        return "无"
    payload = [
        {
            "index": index,
            "name": str(getattr(item, "name", "") or ""),
            "description": str(getattr(item, "description", "") or ""),
            "domain": str(getattr(item, "domain", "") or ""),
        }
        for index, item in enumerate(items, start=1)
    ]
    import json

    return json.dumps(payload, ensure_ascii=False, indent=2)


def _parse_selected_indexes(value: Any, *, available_count: int, reasoning: str) -> list[int]:
    if not isinstance(value, list):
        return []
    result: list[int] = []
    seen: set[int] = set()
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


def _coerce_metadata_list(
    repository: SkillRepository,
    items: list[dict[str, str]],
    *,
    host: str,
) -> list[Any]:
    result: list[Any] = []
    seen_paths: set[str] = set()
    for item in items:
        path = str(item.get("path") or "").strip()
        if not path or not repository.is_llm_eligible_path(path) or path in seen_paths:
            continue
        domain = str(item.get("domain") or "").strip()
        if host and domain and domain != host:
            continue
        seen_paths.add(path)
        result.append(
            type(
                "SeededSkill",
                (),
                {
                    "name": str(item.get("name") or "").strip(),
                    "description": str(item.get("description") or "").strip(),
                    "path": path,
                    "domain": domain,
                },
            )()
        )
    return result[:_MAX_SELECTED_SKILLS]
