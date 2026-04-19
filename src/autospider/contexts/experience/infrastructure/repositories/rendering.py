from __future__ import annotations

import yaml

from autospider.contexts.experience.domain.model import SkillDocument, SkillFieldRule, SkillRuleData


def render_skill_document(document: SkillDocument) -> str:
    rules = document.rules
    frontmatter = dict(document.frontmatter or {})
    if rules.name:
        frontmatter["name"] = rules.name
    if rules.description:
        frontmatter["description"] = rules.description
    lines = ["---"]
    lines.extend(yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip().splitlines())
    lines.extend(["---", "", document.title or f"# {rules.domain} 采集指南", ""])
    lines.extend(_render_basic_info(rules))
    lines.extend(_render_navigation(rules))
    if rules.fields:
        lines.extend(["## 字段提取规则", ""])
        _append_rule_fields(lines, rules.fields)
    if document.insights_markdown.strip():
        lines.extend(["## 站点特征与经验", "", document.insights_markdown.strip(), ""])
    return "\n".join(lines).strip() + "\n"


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
