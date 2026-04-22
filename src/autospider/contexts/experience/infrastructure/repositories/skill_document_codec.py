from __future__ import annotations

import re
from pathlib import Path

import yaml

from autospider.contexts.experience.domain.model import SkillDocument, SkillFieldRule, SkillRuleData


class SkillDocumentParseError(ValueError):
    """Raised when a persisted skill document cannot be parsed safely."""


def domain_to_dirname(domain: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in domain)


def skill_document_path(skills_dir: Path, domain: str) -> Path:
    return skills_dir / domain_to_dirname(domain) / "SKILL.md"


def parse_skill_document(content: str) -> SkillDocument:
    frontmatter, body = _split_frontmatter(content)
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
    return SkillDocument(
        frontmatter=frontmatter,
        title=_parse_title(body),
        rules=rules,
    )


def render_skill_document(document: SkillDocument) -> str:
    rules = document.rules
    frontmatter = dict(document.frontmatter or {})
    if rules.name:
        frontmatter["name"] = rules.name
    if rules.description:
        frontmatter["description"] = rules.description
    lines = ["---"]
    lines.extend(
        yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip().splitlines()
    )
    lines.extend(["---", "", document.title or f"# {rules.domain} 采集指南", ""])
    lines.extend(_render_basic_info(rules))
    lines.extend(_render_navigation(rules))
    if rules.fields:
        lines.extend(["## 字段提取规则", ""])
        _append_rule_fields(lines, rules.fields)
    if document.insights_markdown.strip():
        lines.extend(["## 站点特征与经验", "", document.insights_markdown.strip(), ""])
    return "\n".join(lines).strip() + "\n"


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
                for item in re.findall(
                    r"^- \*\*备选 XPath\*\*:\s*`([^`]+)`$",
                    block,
                    flags=re.MULTILINE,
                )
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


def _render_basic_info(rules: SkillRuleData) -> list[str]:
    lines = ["## 基本信息", ""]
    if rules.list_url:
        lines.append(f"- **列表页 URL**: `{rules.list_url}`")
    if rules.task_description:
        lines.append(f"- **任务描述**: {rules.task_description}")
    if rules.status:
        lines.append(f"- **状态**: {rules.status}")
    if rules.success_rate_text:
        lines.append(f"- **成功率**: {rules.success_rate_text}")
    lines.append("")
    return lines


def _render_navigation(rules: SkillRuleData) -> list[str]:
    if not any(
        [
            rules.detail_xpath,
            rules.pagination_xpath,
            rules.jump_input_selector,
            rules.jump_button_selector,
            rules.nav_steps,
        ]
    ):
        return []
    lines = ["## 列表页导航", ""]
    if rules.detail_xpath:
        lines.append(f"- **详情链接 XPath**: `{rules.detail_xpath}`")
    if rules.pagination_xpath:
        lines.append(f"- **分页控件 XPath**: `{rules.pagination_xpath}`")
    if rules.jump_input_selector:
        lines.append(f"- **跳转输入框**: `{rules.jump_input_selector}`")
    if rules.jump_button_selector:
        lines.append(f"- **跳转按钮**: `{rules.jump_button_selector}`")
    if rules.nav_steps:
        lines.extend(_render_nav_steps(rules.nav_steps))
    lines.append("")
    return lines


def _render_nav_steps(steps: tuple[dict[str, str], ...]) -> list[str]:
    lines = ["### 导航步骤", ""]
    for index, step in enumerate(steps, start=1):
        action = str(step.get("action") or "").strip() or "导航动作"
        description = str(step.get("description") or "").strip()
        line = f"{index}. **{action}**"
        if description:
            line += f" — {description}"
        lines.append(line)
        xpath = str(step.get("xpath") or "").strip()
        value = str(step.get("value") or "").strip()
        if xpath:
            lines.append(f"   - XPath: `{xpath}`")
        if value:
            lines.append(f"   - 值: `{value}`")
    return lines


def _append_rule_fields(lines: list[str], rules: dict[str, SkillFieldRule]) -> None:
    for name, rule in rules.items():
        heading = f"### {name}"
        if rule.description:
            heading += f"（{rule.description}）"
        lines.extend([heading, "", f"- **数据类型**: {rule.data_type or 'text'}"])
        if rule.primary_xpath:
            lines.append(f"- **主 XPath**: `{rule.primary_xpath}`")
        for fallback in rule.fallback_xpaths:
            lines.append(f"- **备选 XPath**: `{fallback}`")
        if rule.extraction_source:
            lines.append(f"- **提取方式**: {rule.extraction_source}")
        if rule.fixed_value:
            lines.append(f"- **固定值**: `{rule.fixed_value}`")
        lines.append(f"- **验证状态**: {'✓ 已验证' if rule.validated else '⚠ 未验证'}")
        lines.append(f"- **置信度**: {rule.confidence}")
        lines.append("")
