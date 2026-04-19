from __future__ import annotations

import re

import yaml

from autospider.contexts.experience.domain.model import SkillDocument, SkillFieldRule, SkillRuleData


class SkillDocumentParseError(ValueError):
    """Raised when a persisted skill document cannot be parsed safely."""


def parse_skill_document(content: str) -> SkillDocument:
    frontmatter, body = _split_frontmatter(content)
    title = _parse_title(body)
    basic = _extract_between_sections(body, "基本信息")
    navigation = _extract_between_sections(body, "列表页导航")
    rules = SkillRuleData(
        domain=_derive_domain(frontmatter),
        name=str(frontmatter.get("name") or "").strip(),
        description=str(frontmatter.get("description") or "").strip(),
        list_url=_clean_code_ticks(_extract_basic_value(basic, "列表页 URL")),
        task_description=_extract_basic_value(basic, "任务描述"),
        status=_extract_status(_extract_basic_value(basic, "状态")),
        success_rate_text=_extract_basic_value(basic, "成功率"),
        detail_xpath=_clean_code_ticks(_extract_basic_value(navigation, "详情链接 XPath")),
        pagination_xpath=_clean_code_ticks(_extract_basic_value(navigation, "分页控件 XPath")),
        jump_input_selector=_clean_code_ticks(_extract_basic_value(navigation, "跳转输入框")),
        jump_button_selector=_clean_code_ticks(_extract_basic_value(navigation, "跳转按钮")),
        nav_steps=tuple(_parse_nav_steps(navigation)),
        fields=_parse_fields(_extract_between_sections(body, "字段提取规则")),
    )
    return SkillDocument(frontmatter=frontmatter, title=title, rules=rules)


def _split_frontmatter(content: str) -> tuple[dict[str, object], str]:
    text = str(content or "")
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise SkillDocumentParseError("frontmatter is not closed with terminating '---'")
    try:
        data = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as exc:
        raise SkillDocumentParseError(f"invalid YAML frontmatter: {exc}") from exc
    if not isinstance(data, dict):
        actual = type(data).__name__
        raise SkillDocumentParseError(f"frontmatter must be a mapping, got {actual}")
    return data, parts[2].lstrip("\n")


def _derive_domain(frontmatter: dict[str, object]) -> str:
    name = str(frontmatter.get("name") or "").strip()
    if name.endswith(" 站点采集"):
        return name.replace(" 站点采集", "").strip()
    return ""


def _parse_title(body: str) -> str:
    match = re.search(r"^#\s+(.+)$", body, flags=re.MULTILINE)
    if match:
        return str(match.group(1) or "").strip()
    return "# 采集指南"


def _extract_between_sections(body: str, header: str) -> str:
    pattern = rf"(?ms)^## {re.escape(header)}\s*$\n(.*?)(?=^## |\Z)"
    match = re.search(pattern, body)
    if not match:
        return ""
    return str(match.group(1) or "").strip()


def _extract_basic_value(section: str, label: str) -> str:
    pattern = rf"^- \*\*{re.escape(label)}\*\*:\s*(.+)$"
    match = re.search(pattern, section, flags=re.MULTILINE)
    if not match:
        return ""
    return str(match.group(1) or "").strip()


def _extract_status(raw_status: str) -> str:
    status = str(raw_status or "").strip()
    if not status:
        return ""
    return status.split()[-1].strip().lower()


def _clean_code_ticks(value: str) -> str:
    text = str(value or "").strip()
    if text.startswith("`") and text.endswith("`") and len(text) >= 2:
        return text[1:-1].strip()
    return text


def _parse_nav_steps(section: str) -> list[dict[str, str]]:
    nav_steps: list[dict[str, str]] = []
    matches = re.finditer(r"^(\d+)\.\s+\*\*(.+?)\*\*(?:\s+—\s+(.*))?$", section, flags=re.MULTILINE)
    current_steps = list(matches)
    lines = section.splitlines()
    for match in current_steps:
        step = {
            "action": str(match.group(2) or "").strip(),
            "description": str(match.group(3) or "").strip(),
        }
        start_line = _line_number(section, match.start())
        next_start = len(lines)
        for candidate in current_steps:
            candidate_line = _line_number(section, candidate.start())
            if candidate_line > start_line:
                next_start = candidate_line
                break
        for line in lines[start_line:next_start]:
            stripped = line.strip()
            if stripped.startswith("- XPath:"):
                step["xpath"] = _clean_code_ticks(stripped.split(":", 1)[1].strip())
            if stripped.startswith("- 值:"):
                step["value"] = _clean_code_ticks(stripped.split(":", 1)[1].strip())
        nav_steps.append(step)
    return nav_steps


def _line_number(text: str, offset: int) -> int:
    return text[:offset].count("\n")


def _parse_fields(section: str) -> dict[str, SkillFieldRule]:
    fields: dict[str, SkillFieldRule] = {}
    matches = re.finditer(r"(?ms)^###\s+(.+?)\s*$\n(.*?)(?=^### |^## |\Z)", section)
    for match in matches:
        heading = str(match.group(1) or "").strip()
        block = str(match.group(2) or "").strip()
        name = heading.split("（", 1)[0].strip()
        description = ""
        if "（" in heading and heading.endswith("）"):
            description = heading.split("（", 1)[1][:-1].strip()
        confidence_raw = _extract_basic_value(block, "置信度")
        fields[name] = SkillFieldRule(
            name=name,
            description=description,
            data_type=_extract_basic_value(block, "数据类型") or "text",
            extraction_source=_extract_basic_value(block, "提取方式"),
            fixed_value=_clean_code_ticks(_extract_basic_value(block, "固定值")),
            primary_xpath=_clean_code_ticks(_extract_basic_value(block, "主 XPath")),
            fallback_xpaths=tuple(
                str(item).strip()
                for item in re.findall(r"^- \*\*备选 XPath\*\*:\s*`([^`]+)`$", block, flags=re.MULTILINE)
                if str(item).strip()
            ),
            validated="已验证" in _extract_basic_value(block, "验证状态"),
            confidence=_parse_confidence(confidence_raw, field_name=name),
        )
    return fields


def _parse_confidence(value: object, *, field_name: str) -> float:
    raw = str(value or "").strip()
    if not raw:
        return 0.0
    try:
        return float(raw)
    except ValueError as exc:
        raise SkillDocumentParseError(
            f"invalid confidence value for field '{field_name}': '{raw}'"
        ) from exc
