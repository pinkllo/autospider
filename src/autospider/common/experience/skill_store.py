"""Skill 文件存储 — 读写标准 Agent Skills 格式的站点采集技能。

标准 Skills 目录结构：
    .agents/skills/{domain}/SKILL.md

SKILL.md 文件格式：
    ---
    name: 技能名称
    description: 技能描述
    ---

    # 采集指南正文...
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from pathlib import Path
from urllib.parse import urlparse

import yaml

from ..logger import get_logger

logger = get_logger(__name__)

_DEFAULT_SKILLS_DIR = ".agents/skills"
_FALLBACK_LIMIT = 5


@dataclass(frozen=True)
class SkillMetadata:
    """供 LLM 暴露的 Skill 元信息。"""

    name: str
    description: str
    path: str
    domain: str


@dataclass(frozen=True)
class SkillFieldRule:
    """结构化字段提取规则。"""

    name: str
    description: str = ""
    data_type: str = "text"
    extraction_source: str = ""
    fixed_value: str = ""
    primary_xpath: str = ""
    fallback_xpaths: list[str] = field(default_factory=list)
    validated: bool = False
    confidence: float = 0.0


@dataclass(frozen=True)
class SkillRuleData:
    """结构化规则层。"""

    domain: str = ""
    name: str = ""
    description: str = ""
    list_url: str = ""
    task_description: str = ""
    status: str = ""
    success_rate: float = 0.0
    success_rate_text: str = ""
    detail_xpath: str = ""
    pagination_xpath: str = ""
    jump_input_selector: str = ""
    jump_button_selector: str = ""
    nav_steps: list[dict[str, str]] = field(default_factory=list)
    subtask_names: list[str] = field(default_factory=list)
    fields: dict[str, SkillFieldRule] = field(default_factory=dict)


@dataclass(frozen=True)
class SkillDocument:
    """Skill 文档：规则层 + 可编辑经验层。"""

    frontmatter: dict[str, object]
    title: str
    rules: SkillRuleData
    insights_markdown: str = ""


def _domain_to_dirname(domain: str) -> str:
    """将域名转换为安全的目录名。"""
    return re.sub(r"[^a-zA-Z0-9._-]", "_", domain)


def _normalize_host(host: str) -> str:
    """归一化 host，移除端口与尾随点。"""
    value = str(host or "").strip().lower()
    if not value:
        return ""
    if "@" in value:
        value = value.rsplit("@", 1)[-1]
    if ":" in value and not value.startswith("["):
        value = value.split(":", 1)[0]
    return value.rstrip(".")


def _extract_domain(url: str) -> str:
    """从 URL 中提取归一化域名。"""
    try:
        parsed = urlparse(url)
        host = parsed.netloc or parsed.path.split("/")[0]
        return _normalize_host(host)
    except Exception:
        return ""


def _split_frontmatter(content: str) -> tuple[dict[str, object], str]:
    """拆分 frontmatter 与正文。"""
    text = str(content or "")
    if not text.startswith("---"):
        return {}, text

    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text

    try:
        data = yaml.safe_load(parts[1]) or {}
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    return data, parts[2].lstrip("\n")


def _parse_frontmatter(content: str) -> dict[str, str]:
    """提取 SKILL.md frontmatter 中的 name/description。"""
    data, _ = _split_frontmatter(content)
    return {
        "name": str(data.get("name") or "").strip(),
        "description": str(data.get("description") or "").strip(),
    }


def _is_draft_skill_path(path: str | Path) -> bool:
    """仅按路径判断 Skill 是否为 output/draft_skills 下的草稿。"""
    parts = [part.lower() for part in Path(path).parts]
    for index, part in enumerate(parts):
        if part != "output":
            continue
        if index + 1 < len(parts) and parts[index + 1] == "draft_skills":
            return True
    return False


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


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


def _parse_success_rate(raw: str) -> tuple[float, str]:
    text = str(raw or "").strip()
    if not text:
        return 0.0, ""
    match = re.search(r"(\d+)%", text)
    if not match:
        return 0.0, text
    try:
        return int(match.group(1)) / 100, text
    except Exception:
        return 0.0, text


def _clean_code_ticks(value: str) -> str:
    text = str(value or "").strip()
    if text.startswith("`") and text.endswith("`") and len(text) >= 2:
        return text[1:-1].strip()
    return text


def _dedupe_xpaths(values: list[str], *, exclude: set[str] | None = None, limit: int = _FALLBACK_LIMIT) -> list[str]:
    unique: list[str] = []
    seen = {item for item in (exclude or set()) if item}
    for raw in values:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        unique.append(value)
        if len(unique) >= limit:
            break
    return unique


def _parse_title(body: str, fallback_domain: str) -> str:
    match = re.search(r"^#\s+(.+)$", body, flags=re.MULTILINE)
    if match:
        return str(match.group(1) or "").strip()
    return f"{fallback_domain} 采集指南" if fallback_domain else "采集指南"


def _parse_list_nav(section: str) -> tuple[str, str, str, list[dict[str, str]]]:
    detail_xpath = ""
    detail_match = re.search(r"```xpath\n(.*?)\n```", section, flags=re.DOTALL)
    if detail_match:
        detail_xpath = str(detail_match.group(1) or "").strip()

    pagination_xpath = ""
    pagination_match = re.search(r"^分页控件 XPath:\s*`([^`]+)`$", section, flags=re.MULTILINE)
    if pagination_match:
        pagination_xpath = str(pagination_match.group(1) or "").strip()

    jump_input = ""
    jump_button = ""
    for line in section.splitlines():
        stripped = line.strip()
        if stripped.startswith("1. 在页码输入框中输入目标页码"):
            match = re.search(r"`([^`]+)`", stripped)
            if match:
                jump_input = str(match.group(1) or "").strip()
        elif stripped.startswith("2. 点击跳转按钮"):
            match = re.search(r"`([^`]+)`", stripped)
            if match:
                jump_button = str(match.group(1) or "").strip()

    nav_steps: list[dict[str, str]] = []
    nav_match = re.search(r"(?ms)^### 导航步骤\s*$\n(.*)$", section)
    if nav_match:
        raw_lines = [line.rstrip() for line in str(nav_match.group(1) or "").splitlines()]
        current: dict[str, str] | None = None
        for line in raw_lines:
            stripped = line.strip()
            heading_match = re.match(r"^(\d+)\.\s+\*\*(.+?)\*\*(?:\s+—\s+(.*))?$", stripped)
            if heading_match:
                if current:
                    nav_steps.append(current)
                current = {
                    "action": str(heading_match.group(2) or "").strip(),
                    "description": str(heading_match.group(3) or "").strip(),
                }
                continue
            if current is None:
                continue
            if stripped.startswith("- XPath:"):
                current["xpath"] = _clean_code_ticks(stripped.split(":", 1)[1].strip())
            elif stripped.startswith("- 值:"):
                current["value"] = _clean_code_ticks(stripped.split(":", 1)[1].strip())
        if current:
            nav_steps.append(current)

    return detail_xpath, pagination_xpath, jump_input, jump_button, nav_steps


def _parse_fields(section: str) -> dict[str, SkillFieldRule]:
    fields: dict[str, SkillFieldRule] = {}
    if not section:
        return fields

    matches = list(re.finditer(r"(?ms)^###\s+(.+?)\s*$\n(.*?)(?=^### |^## |\Z)", section))
    for match in matches:
        heading = str(match.group(1) or "").strip()
        block = str(match.group(2) or "").strip()
        name = heading.split("（", 1)[0].strip()
        description = ""
        if "（" in heading and heading.endswith("）"):
            description = heading.split("（", 1)[1][:-1].strip()

        data_type = _extract_basic_value(block, "数据类型")
        extraction_source = _extract_basic_value(block, "提取方式")
        fixed_value = _clean_code_ticks(_extract_basic_value(block, "固定值"))
        primary_xpath = _clean_code_ticks(_extract_basic_value(block, "主 XPath"))
        fallback_xpaths = [
            str(item).strip()
            for item in re.findall(r"^- \*\*备选 XPath\*\*:\s*`([^`]+)`$", block, flags=re.MULTILINE)
            if str(item).strip()
        ]
        validated = "已验证" in _extract_basic_value(block, "验证状态")
        confidence = _safe_float(_extract_basic_value(block, "置信度"), 0.0)

        fields[name] = SkillFieldRule(
            name=name,
            description=description,
            data_type=data_type or "text",
            extraction_source=extraction_source,
            fixed_value=fixed_value,
            primary_xpath=primary_xpath,
            fallback_xpaths=fallback_xpaths,
            validated=validated,
            confidence=confidence,
        )
    return fields


def parse_skill_document(content: str) -> SkillDocument:
    frontmatter, body = _split_frontmatter(content)
    name = str(frontmatter.get("name") or "").strip()
    description = str(frontmatter.get("description") or "").strip()
    domain = name.replace(" 站点采集", "").strip() if name.endswith(" 站点采集") else ""

    title = _parse_title(body, domain)
    basic_info = _extract_between_sections(body, "基本信息")
    list_url = _clean_code_ticks(_extract_basic_value(basic_info, "列表页 URL"))
    task_description = _extract_basic_value(basic_info, "任务描述")
    raw_status = _extract_basic_value(basic_info, "状态")
    status = raw_status.split()[-1].strip().lower() if raw_status else ""
    success_rate, success_rate_text = _parse_success_rate(_extract_basic_value(basic_info, "成功率"))

    list_nav = _extract_between_sections(body, "列表页导航")
    detail_xpath, pagination_xpath, jump_input, jump_button, nav_steps = _parse_list_nav(list_nav)
    fields = _parse_fields(_extract_between_sections(body, "字段提取规则"))
    insights_markdown = _extract_between_sections(body, "站点特征与经验")

    rules = SkillRuleData(
        domain=domain,
        name=name,
        description=description,
        list_url=list_url,
        task_description=task_description,
        status=status,
        success_rate=success_rate,
        success_rate_text=success_rate_text,
        detail_xpath=detail_xpath,
        pagination_xpath=pagination_xpath,
        jump_input_selector=jump_input,
        jump_button_selector=jump_button,
        nav_steps=nav_steps,
        subtask_names=[
            line[2:].strip()
            for line in _extract_between_sections(body, "子任务").splitlines()
            if line.strip().startswith("- ")
        ],
        fields=fields,
    )
    return SkillDocument(
        frontmatter=frontmatter,
        title=title,
        rules=rules,
        insights_markdown=insights_markdown,
    )


def render_skill_document(document: SkillDocument) -> str:
    rules = document.rules
    frontmatter = dict(document.frontmatter or {})
    if rules.name:
        frontmatter["name"] = rules.name
    if rules.description:
        frontmatter["description"] = rules.description

    lines: list[str] = ["---"]
    lines.extend(yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip().splitlines())
    lines.extend(["---", "", document.title or f"# {rules.domain} 采集指南", ""])

    lines.append("## 基本信息")
    lines.append("")
    if rules.list_url:
        lines.append(f"- **列表页 URL**: `{rules.list_url}`")
    if rules.task_description:
        lines.append(f"- **任务描述**: {rules.task_description}")
    if rules.status:
        status_icon = "✅" if rules.status == "validated" else "📝"
        lines.append(f"- **状态**: {status_icon} {rules.status}")
    if rules.success_rate_text:
        lines.append(f"- **成功率**: {rules.success_rate_text}")
    lines.append("")

    has_nav = (
        rules.detail_xpath
        or rules.pagination_xpath
        or rules.jump_input_selector
        or rules.jump_button_selector
        or rules.nav_steps
    )
    if has_nav:
        lines.append("## 列表页导航")
        lines.append("")
        if rules.detail_xpath:
            lines.append("### 详情链接定位")
            lines.append("")
            lines.append("使用以下 XPath 从列表页中定位每个详情条目的入口：")
            lines.append("")
            lines.append("```xpath")
            lines.append(rules.detail_xpath)
            lines.append("```")
            lines.append("")
        if rules.jump_input_selector or rules.jump_button_selector:
            lines.append("### 分页处理（跳转式）")
            lines.append("")
            lines.append("本站使用跳转式分页控件，操作步骤：")
            lines.append("")
            if rules.jump_input_selector:
                lines.append(f"1. 在页码输入框中输入目标页码，选择器: `{rules.jump_input_selector}`")
            if rules.jump_button_selector:
                lines.append(f"2. 点击跳转按钮，选择器: `{rules.jump_button_selector}`")
            lines.append("")
        elif rules.pagination_xpath:
            lines.append("### 分页处理")
            lines.append("")
            lines.append(f"分页控件 XPath: `{rules.pagination_xpath}`")
            lines.append("")
        if rules.nav_steps:
            lines.append("### 导航步骤")
            lines.append("")
            for index, step in enumerate(rules.nav_steps, start=1):
                action = str(step.get("action") or "").strip()
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
            lines.append("")

    if rules.fields:
        lines.append("## 字段提取规则")
        lines.append("")
        for field_name, rule in rules.fields.items():
            heading = f"### {field_name}"
            if rule.description:
                heading += f"（{rule.description}）"
            lines.append(heading)
            lines.append("")
            lines.append(f"- **数据类型**: {rule.data_type or 'text'}")
            if rule.extraction_source in {"constant", "subtask_context"}:
                lines.append(f"- **提取方式**: {rule.extraction_source}")
                if rule.fixed_value:
                    lines.append(f"- **固定值**: `{rule.fixed_value}`")
            elif rule.primary_xpath:
                lines.append(f"- **主 XPath**: `{rule.primary_xpath}`")
                for fallback in rule.fallback_xpaths:
                    lines.append(f"- **备选 XPath**: `{fallback}`")
            status_mark = "✓ 已验证" if rule.validated else "⚠ 未验证"
            lines.append(f"- **验证状态**: {status_mark}")
            lines.append(f"- **置信度**: {rule.confidence}")
            lines.append("")

    if document.insights_markdown.strip():
        lines.append("## 站点特征与经验")
        lines.append("")
        lines.append(document.insights_markdown.strip())
        lines.append("")

    if rules.subtask_names:
        lines.append("## 子任务")
        lines.append("")
        lines.append(f"本站共 {len(rules.subtask_names)} 个子任务分类：")
        lines.append("")
        for subtask_name in rules.subtask_names:
            lines.append(f"- {subtask_name}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def _merge_field_rule(existing: SkillFieldRule, incoming: SkillFieldRule) -> SkillFieldRule:
    if existing.validated and not incoming.validated:
        return existing
    if existing.validated and incoming.validated and incoming.confidence < existing.confidence:
        return existing

    if not incoming.primary_xpath:
        return incoming

    fallback_xpaths = _dedupe_xpaths(
        [*incoming.fallback_xpaths, existing.primary_xpath, *existing.fallback_xpaths],
        exclude={incoming.primary_xpath},
    )
    return SkillFieldRule(
        name=incoming.name,
        description=incoming.description,
        data_type=incoming.data_type,
        extraction_source=incoming.extraction_source,
        fixed_value=incoming.fixed_value,
        primary_xpath=incoming.primary_xpath,
        fallback_xpaths=fallback_xpaths,
        validated=incoming.validated,
        confidence=incoming.confidence,
    )


def merge_skill_documents(existing: SkillDocument, incoming: SkillDocument) -> SkillDocument:
    existing_rules = existing.rules
    incoming_rules = incoming.rules

    if existing_rules.status == "validated":
        if incoming_rules.status != "validated":
            return SkillDocument(
                frontmatter=existing.frontmatter,
                title=existing.title,
                rules=existing.rules,
                insights_markdown=incoming.insights_markdown or existing.insights_markdown,
            )
        if incoming_rules.success_rate < existing_rules.success_rate:
            return SkillDocument(
                frontmatter=existing.frontmatter,
                title=existing.title,
                rules=existing.rules,
                insights_markdown=incoming.insights_markdown or existing.insights_markdown,
            )

    merged_fields: dict[str, SkillFieldRule] = {}
    all_field_names = list(existing_rules.fields.keys())
    for name in incoming_rules.fields.keys():
        if name not in all_field_names:
            all_field_names.append(name)

    for field_name in all_field_names:
        existing_field = existing_rules.fields.get(field_name)
        incoming_field = incoming_rules.fields.get(field_name)
        if existing_field and incoming_field:
            merged_fields[field_name] = _merge_field_rule(existing_field, incoming_field)
        elif incoming_field:
            merged_fields[field_name] = incoming_field
        elif existing_field:
            merged_fields[field_name] = existing_field

    merged_rules = SkillRuleData(
        domain=incoming_rules.domain or existing_rules.domain,
        name=incoming_rules.name or existing_rules.name,
        description=incoming_rules.description or existing_rules.description,
        list_url=incoming_rules.list_url or existing_rules.list_url,
        task_description=incoming_rules.task_description or existing_rules.task_description,
        status=incoming_rules.status or existing_rules.status,
        success_rate=max(incoming_rules.success_rate, existing_rules.success_rate),
        success_rate_text=incoming_rules.success_rate_text or existing_rules.success_rate_text,
        detail_xpath=incoming_rules.detail_xpath or existing_rules.detail_xpath,
        pagination_xpath=incoming_rules.pagination_xpath or existing_rules.pagination_xpath,
        jump_input_selector=incoming_rules.jump_input_selector or existing_rules.jump_input_selector,
        jump_button_selector=incoming_rules.jump_button_selector or existing_rules.jump_button_selector,
        nav_steps=incoming_rules.nav_steps or existing_rules.nav_steps,
        subtask_names=incoming_rules.subtask_names or existing_rules.subtask_names,
        fields=merged_fields,
    )

    merged_frontmatter = dict(existing.frontmatter or {})
    merged_frontmatter.update(incoming.frontmatter or {})
    merged_frontmatter["name"] = merged_rules.name
    merged_frontmatter["description"] = merged_rules.description

    return SkillDocument(
        frontmatter=merged_frontmatter,
        title=incoming.title or existing.title,
        rules=merged_rules,
        insights_markdown=incoming.insights_markdown or existing.insights_markdown,
    )


class SkillStore:
    """标准 Agent Skills 格式的站点采集技能存储。

    每个站点域名对应一个技能目录，内含标准的 SKILL.md 文件。
    """

    def __init__(self, skills_dir: str | Path | None = None):
        if skills_dir:
            self.skills_dir = Path(skills_dir)
        else:
            self.skills_dir = self._find_project_root() / _DEFAULT_SKILLS_DIR
        self.skills_dir.mkdir(parents=True, exist_ok=True)

    def save_document(self, domain: str, document: SkillDocument) -> Path:
        """保存结构化 Skill 文档。"""
        dirname = _domain_to_dirname(domain)
        skill_dir = self.skills_dir / dirname
        skill_dir.mkdir(parents=True, exist_ok=True)
        filepath = skill_dir / "SKILL.md"

        final_document = document
        existing_content = self.load(domain)
        if existing_content:
            existing_doc = parse_skill_document(existing_content)
            final_document = merge_skill_documents(existing_doc, document)

        final_content = render_skill_document(final_document).strip()
        temp_path = filepath.with_suffix(".md.tmp")
        temp_path.write_text(final_content + "\n", encoding="utf-8")
        temp_path.replace(filepath)

        logger.info("[SkillStore] Skill 已保存: %s", filepath)
        return filepath

    def save(self, domain: str, content: str) -> Path:
        """保存标准 SKILL.md 文件。"""
        incoming_doc = parse_skill_document(content)
        return self.save_document(domain, incoming_doc)

    def load(self, domain: str) -> str | None:
        """按域名加载 Skill 内容。

        Returns:
            SKILL.md 的完整文本内容，或 None。
        """
        dirname = _domain_to_dirname(domain)
        filepath = self.skills_dir / dirname / "SKILL.md"
        if not filepath.exists():
            return None

        try:
            return filepath.read_text(encoding="utf-8")
        except Exception as exc:
            logger.debug("[SkillStore] 读取文件失败 %s: %s", filepath, exc)
            return None

    def load_by_path(self, path: str | Path) -> str | None:
        """按文件路径加载 Skill 内容。"""
        filepath = Path(path)
        if not filepath.exists():
            return None

        try:
            return filepath.read_text(encoding="utf-8")
        except Exception as exc:
            logger.debug("[SkillStore] 读取文件失败 %s: %s", filepath, exc)
            return None

    def is_llm_eligible_path(self, path: str | Path) -> bool:
        """判断指定 Skill 文件是否可以暴露给 LLM。"""
        filepath = Path(path)
        if not filepath.exists():
            return False
        return not _is_draft_skill_path(filepath)

    def find_by_url(self, url: str) -> str | None:
        """按 URL 查找精确 host 匹配的 Skill。

        Returns:
            SKILL.md 的完整文本内容，或 None。
        """
        domain = _extract_domain(url)
        if not domain:
            return None
        return self.load(domain)

    def list_by_url(self, url: str) -> list[SkillMetadata]:
        """按 URL 枚举同一 host 下的所有 Skill 元信息。"""
        domain = _extract_domain(url)
        if not domain:
            return []
        return self.list_by_domain(domain)

    def list_by_domain(self, domain: str) -> list[SkillMetadata]:
        """按精确 host 枚举所有 Skill 元信息。"""
        target = _extract_domain(domain) or _normalize_host(domain)
        if not target:
            return []

        matched: list[SkillMetadata] = []
        for child in sorted(self.skills_dir.iterdir()):
            if not child.is_dir():
                continue
            skill_file = child / "SKILL.md"
            if not skill_file.exists():
                continue

            child_domain = _normalize_host(child.name)
            if child_domain != target:
                continue

            meta = self._load_metadata(skill_file=skill_file, domain=child_domain)
            if meta is not None:
                matched.append(meta)

        return matched

    def list_all(self) -> list[str]:
        """列出所有已存储的 Skill 域名。"""
        domains: list[str] = []
        for child in sorted(self.skills_dir.iterdir()):
            if child.is_dir() and (child / "SKILL.md").exists():
                domains.append(child.name)
        return domains

    def list_all_metadata(self) -> list[SkillMetadata]:
        """列出所有 Skill 的 name/description/path 元信息。"""
        items: list[SkillMetadata] = []
        for child in sorted(self.skills_dir.iterdir()):
            if not child.is_dir():
                continue
            skill_file = child / "SKILL.md"
            if not skill_file.exists():
                continue
            meta = self._load_metadata(skill_file=skill_file, domain=_normalize_host(child.name))
            if meta is not None:
                items.append(meta)
        return items

    def _find_project_root(self) -> Path:
        """向上查找项目根目录（含 pyproject.toml 或 .git 的目录）。"""
        current = Path(__file__).resolve()
        for parent in current.parents:
            if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
                return parent
        return Path.cwd()

    def _load_metadata(self, *, skill_file: Path, domain: str) -> SkillMetadata | None:
        """从 skill 文件加载元信息。"""
        if not self.is_llm_eligible_path(skill_file):
            logger.debug("[SkillStore] 跳过 draft skill 路径（不暴露给 LLM）: %s", skill_file)
            return None

        content = self.load_by_path(skill_file)
        if not content:
            return None

        frontmatter = _parse_frontmatter(content)
        name = frontmatter.get("name", "")
        description = frontmatter.get("description", "")
        if not name or not description:
            logger.debug("[SkillStore] Skill frontmatter 不完整: %s", skill_file)
            return None

        return SkillMetadata(
            name=name,
            description=description,
            path=str(skill_file),
            domain=domain,
        )
