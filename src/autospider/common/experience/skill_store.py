"""Skill 文件存储 — 读写和检索 Spider Skill Markdown 文件。

Skill 文件格式：
```markdown
---
domain: example.com
list_url: https://example.com/news
fields_experience:
  - field_name: title
    ...
---

# 站点特征与避坑指南
- ...
```
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from ..logger import get_logger

logger = get_logger(__name__)

# 默认 Skill 存储目录（项目根目录下）
_DEFAULT_SKILLS_DIR = ".agents/site_skills"


def _domain_to_filename(domain: str) -> str:
    """将域名转换为安全的文件名。"""
    return re.sub(r"[^a-zA-Z0-9._-]", "_", domain)


def _extract_domain(url: str) -> str:
    """从 URL 中提取域名。"""
    try:
        parsed = urlparse(url)
        return parsed.netloc or parsed.path.split("/")[0]
    except Exception:
        return ""


class SkillStore:
    """Skill 文件的读写管理器。

    负责：
    - 将 SiteSkill 对象序列化为 YAML+Markdown 文件
    - 从文件反序列化为 SiteSkill 对象
    - 按域名/URL 检索匹配的 Skill
    """

    def __init__(self, skills_dir: str | Path | None = None):
        """初始化。

        Args:
            skills_dir: Skill 文件存储目录。默认为项目根目录下的 .agents/site_skills/
        """
        if skills_dir:
            self.skills_dir = Path(skills_dir)
        else:
            # 尝试找到项目根目录
            self.skills_dir = self._find_project_root() / _DEFAULT_SKILLS_DIR
        self.skills_dir.mkdir(parents=True, exist_ok=True)

    def save(self, skill_data: dict[str, Any], insights_markdown: str = "") -> Path:
        """将 Skill 数据保存为 YAML + Markdown 文件。

        Args:
            skill_data: 结构化数据（写入 YAML frontmatter）
            insights_markdown: LLM 生成的软经验文本（写入 Markdown 正文）

        Returns:
            保存的文件路径
        """
        domain = str(skill_data.get("domain") or "")
        if not domain:
            url = str(skill_data.get("list_url") or "")
            domain = _extract_domain(url) or "unknown"
            skill_data["domain"] = domain

        filename = _domain_to_filename(domain) + ".md"
        filepath = self.skills_dir / filename

        # 序列化 YAML frontmatter
        yaml_str = yaml.dump(
            skill_data,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )

        # 组装文件内容
        content_parts = [
            "---",
            yaml_str.rstrip(),
            "---",
            "",
        ]

        if insights_markdown:
            content_parts.append(insights_markdown.strip())
            content_parts.append("")

        content = "\n".join(content_parts)

        # 原子写入
        filepath.parent.mkdir(parents=True, exist_ok=True)
        temp_path = filepath.with_suffix(".md.tmp")
        temp_path.write_text(content, encoding="utf-8")
        temp_path.replace(filepath)

        logger.info("[SkillStore] Skill 已保存: %s", filepath)
        return filepath

    def load(self, domain: str) -> tuple[dict[str, Any], str] | None:
        """按域名加载 Skill。

        Returns:
            (结构化数据, Markdown 正文) 或 None
        """
        filename = _domain_to_filename(domain) + ".md"
        filepath = self.skills_dir / filename
        if not filepath.exists():
            return None

        return self._parse_skill_file(filepath)

    def find_by_url(self, url: str) -> tuple[dict[str, Any], str] | None:
        """按 URL 查找匹配的 Skill（通过域名匹配）。

        Returns:
            (结构化数据, Markdown 正文) 或 None
        """
        domain = _extract_domain(url)
        if not domain:
            return None
        return self.load(domain)

    def list_all(self) -> list[str]:
        """列出所有已存储的 Skill 域名。"""
        domains: list[str] = []
        for filepath in self.skills_dir.glob("*.md"):
            parsed = self._parse_skill_file(filepath)
            if parsed:
                data, _ = parsed
                domain = str(data.get("domain") or filepath.stem)
                domains.append(domain)
        return domains

    def _parse_skill_file(self, filepath: Path) -> tuple[dict[str, Any], str] | None:
        """解析 YAML frontmatter + Markdown 文件。"""
        try:
            text = filepath.read_text(encoding="utf-8")
        except Exception as exc:
            logger.debug("[SkillStore] 读取文件失败 %s: %s", filepath, exc)
            return None

        # 解析 YAML frontmatter
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)", text, re.DOTALL)
        if not match:
            logger.debug("[SkillStore] 文件格式不正确（缺少 YAML frontmatter）: %s", filepath)
            return None

        yaml_text = match.group(1)
        markdown_text = match.group(2).strip()

        try:
            data = yaml.safe_load(yaml_text) or {}
        except yaml.YAMLError as exc:
            logger.debug("[SkillStore] YAML 解析失败 %s: %s", filepath, exc)
            return None

        return data, markdown_text

    def _find_project_root(self) -> Path:
        """向上查找项目根目录（含 pyproject.toml 或 .git 的目录）。"""
        current = Path(__file__).resolve()
        for parent in current.parents:
            if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
                return parent
        # 回退：使用当前工作目录
        return Path.cwd()
