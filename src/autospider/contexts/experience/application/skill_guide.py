from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

import yaml

_MAX_SECTION_ITEMS = 6
_MAX_SUBTASK_NAMES = 8
_RISKY_ABSOLUTE_XPATH_SEGMENTS = 8
_POSITIONAL_INDEX_PATTERN = re.compile(r"\[\d+\]")


class SkillGuideCandidate(Protocol):
    domain: str
    list_url: str
    task_description: str
    summary: dict[str, Any]
    collection_config: dict[str, Any]
    extraction_config: dict[str, Any]
    extraction_evidence: list[dict[str, Any]]
    validation_failures: list[dict[str, Any]]
    plan_knowledge: str
    subtask_names: list[str]
    page_state_signature: str
    variant_label: str
    context: dict[str, str]


@dataclass(frozen=True, slots=True)
class SkillGuideDraft:
    name: str
    description: str
    scope: tuple[str, ...]
    page_traits: tuple[str, ...]
    collection_strategy: tuple[str, ...]
    field_hints: tuple[str, ...]
    avoid: tuple[str, ...]


def build_skill_guide(candidate: SkillGuideCandidate) -> SkillGuideDraft:
    domain = _clean(candidate.domain)
    name = f"{domain} 采集指导" if domain else "站点采集指导"
    description = _build_description(domain, candidate)
    fields = _collect_field_items(candidate)
    collection_config = dict(candidate.collection_config or {})
    validation_failures = list(candidate.validation_failures or [])
    return SkillGuideDraft(
        name=name,
        description=description,
        scope=_scope_items(candidate),
        page_traits=_page_trait_items(candidate, collection_config),
        collection_strategy=_strategy_items(candidate, collection_config),
        field_hints=_field_hint_items(fields),
        avoid=_avoid_items(candidate, collection_config, fields, validation_failures),
    )


def render_skill_guide_markdown(guide: SkillGuideDraft) -> str:
    frontmatter = yaml.safe_dump(
        {"name": guide.name, "description": guide.description},
        allow_unicode=True,
        sort_keys=False,
    ).strip()
    lines = ["---", frontmatter, "---", "", f"# {guide.name}", ""]
    _append_section(lines, "适用范围", guide.scope)
    _append_section(lines, "页面特征", guide.page_traits)
    _append_section(lines, "采集策略", guide.collection_strategy)
    _append_section(lines, "字段提示", guide.field_hints)
    _append_section(lines, "避免事项", guide.avoid)
    return "\n".join(lines).strip() + "\n"


def _build_description(domain: str, candidate: SkillGuideCandidate) -> str:
    task = _clean(candidate.task_description)
    if task:
        return f"{domain} 的轻量采集指导：{task}" if domain else f"轻量采集指导：{task}"
    return f"{domain} 的轻量采集指导。" if domain else "轻量采集指导。"


def _scope_items(candidate: SkillGuideCandidate) -> tuple[str, ...]:
    items = [
        f"适用于 `{_clean(candidate.list_url)}`。" if _clean(candidate.list_url) else "",
        "仅作为采集先验；当前截图、DOM 和用户任务优先。",
    ]
    task = _clean(candidate.task_description)
    if task:
        items.append(f"当前经验来自任务：{task}")
    return _dedupe_items(items)


def _page_trait_items(
    candidate: SkillGuideCandidate,
    collection_config: dict[str, Any],
) -> tuple[str, ...]:
    text = f"{candidate.list_url}\n{candidate.plan_knowledge}"
    items = [
        _hash_route_trait(text, candidate),
        _dimension_trait(text),
        _subtask_trait(candidate.subtask_names),
        _pagination_trait(collection_config),
    ]
    return _dedupe_items(items)


def _strategy_items(
    candidate: SkillGuideCandidate,
    collection_config: dict[str, Any],
) -> tuple[str, ...]:
    items = ["先确认当前页面状态、业务领域和用户任务匹配，再展开采集。"]
    names = _preview_names(candidate.subtask_names)
    if names:
        items.append(f"如果任务要求按分类或子任务采集，可围绕 {names} 展开。")
    if _clean(collection_config.get("detail_xpath")) or _clean(
        collection_config.get("common_detail_xpath")
    ):
        items.append("详情链接规则只能作为历史线索，复用前先在当前页面验证命中结果。")
    if _has_navigation(collection_config):
        items.append("涉及点击、切换或翻页时，按当前可见控件重新确认导航步骤。")
    return _dedupe_items(items)


def _field_hint_items(fields: list[dict[str, Any]]) -> tuple[str, ...]:
    items: list[str] = []
    for field in fields:
        name = _clean(field.get("name"))
        if not name:
            continue
        items.append(_field_hint(field, name))
        if len(items) >= _MAX_SECTION_ITEMS:
            break
    if not items:
        items.append("字段位置需要以当前页面 DOM 为准，不要直接套用历史 XPath。")
    return _dedupe_items(items)


def _avoid_items(
    candidate: SkillGuideCandidate,
    collection_config: dict[str, Any],
    fields: list[dict[str, Any]],
    validation_failures: list[dict[str, Any]],
) -> tuple[str, ...]:
    items = [
        "不要把历史 XPath 当成当前页面事实；复用前必须在当前 DOM 命中验证。",
        _subtask_avoidance(candidate.subtask_names),
        _context_avoidance(candidate.context),
        _risky_xpath_avoidance(collection_config, fields),
        _validation_failure_avoidance(validation_failures),
    ]
    return _dedupe_items(items)


def _collect_field_items(candidate: SkillGuideCandidate) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    sources = [
        list(dict(candidate.extraction_config or {}).get("fields") or []),
        list(candidate.extraction_evidence or []),
        list(dict(candidate.summary or {}).get("fields") or []),
    ]
    for source in sources:
        for raw in source:
            if not isinstance(raw, dict):
                continue
            name = _clean(raw.get("name"))
            if not name or name in seen:
                continue
            seen.add(name)
            items.append(dict(raw))
    return items


def _field_hint(field: dict[str, Any], name: str) -> str:
    source = _clean(field.get("extraction_source"))
    fixed_value = _clean(field.get("fixed_value"))
    description = _clean(field.get("description"))
    if source == "subtask_context" or fixed_value:
        return f"`{name}` 优先从当前子任务、分类或任务上下文继承。"
    if description:
        return f"`{name}`（{description}）需要按当前页面 DOM 重新确认。"
    return f"`{name}` 需要按当前页面 DOM 重新确认。"


def _hash_route_trait(text: str, candidate: SkillGuideCandidate) -> str:
    if "#" not in text and not _clean(candidate.page_state_signature):
        return ""
    return "页面可能使用 SPA/hash 路由或前端状态切换，页面状态需以当前页面为准。"


def _dimension_trait(text: str) -> str:
    if "业务领域" in text and "相关分类" in text:
        return "业务领域、相关分类等筛选维度需要分清，避免混用。"
    if "左侧" in text and "分类" in text:
        return "左侧导航和页面内分类入口可能属于不同维度，拆分前需要确认语义。"
    return ""


def _subtask_trait(names: list[str]) -> str:
    preview = _preview_names(names)
    if not preview:
        return ""
    return f"历史运行曾识别出这些子任务或分类：{preview}。"


def _pagination_trait(collection_config: dict[str, Any]) -> str:
    if not _clean(collection_config.get("pagination_xpath")):
        return ""
    return "页面存在分页入口时，应以当前可见控件确认翻页方式。"


def _has_navigation(collection_config: dict[str, Any]) -> bool:
    return any(
        [
            bool(collection_config.get("nav_steps")),
            bool(_clean(collection_config.get("pagination_xpath"))),
            bool(_clean(collection_config.get("jump_input_selector"))),
            bool(_clean(collection_config.get("jump_button_selector"))),
        ]
    )


def _subtask_avoidance(names: list[str]) -> str:
    if not names:
        return ""
    return "不要把同层分类入口继续误拆成更深层分类。"


def _context_avoidance(context: dict[str, str]) -> str:
    raw = _clean(dict(context or {}).get("do_not"))
    if not raw:
        return ""
    return raw.strip("[]'\"")


def _risky_xpath_avoidance(
    collection_config: dict[str, Any],
    fields: list[dict[str, Any]],
) -> str:
    xpaths = [_clean(collection_config.get("detail_xpath"))]
    xpaths.append(_clean(collection_config.get("common_detail_xpath")))
    xpaths.extend(_clean(field.get("xpath") or field.get("primary_xpath")) for field in fields)
    if any(_is_risky_xpath(xpath) for xpath in xpaths):
        return "不要把只命中首行、带位置序号或过长绝对路径的 XPath 当成通用规则。"
    return ""


def _validation_failure_avoidance(validation_failures: list[dict[str, Any]]) -> str:
    names = []
    for item in validation_failures:
        if isinstance(item, dict):
            names.append(_clean(item.get("field_name") or item.get("field")))
    preview = _preview_names([name for name in names if name])
    if not preview:
        return ""
    return f"字段 {preview} 曾出现验证失败，复用时优先重新确认。"


def _is_risky_xpath(xpath: str) -> bool:
    value = _clean(xpath)
    if not value:
        return False
    if _POSITIONAL_INDEX_PATTERN.search(value):
        return True
    return value.startswith("/") and value.count("/") >= _RISKY_ABSOLUTE_XPATH_SEGMENTS


def _append_section(lines: list[str], title: str, items: tuple[str, ...]) -> None:
    lines.extend([f"## {title}", ""])
    for item in items:
        lines.append(f"- {item}")
    lines.append("")


def _dedupe_items(items: list[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in items:
        item = _clean(raw)
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
        if len(result) >= _MAX_SECTION_ITEMS:
            break
    return tuple(result)


def _preview_names(names: list[str]) -> str:
    cleaned = [_clean(name) for name in names if _clean(name)]
    if not cleaned:
        return ""
    preview = " / ".join(cleaned[:_MAX_SUBTASK_NAMES])
    if len(cleaned) > _MAX_SUBTASK_NAMES:
        return f"{preview} 等"
    return preview


def _clean(value: object) -> str:
    return str(value or "").strip()
