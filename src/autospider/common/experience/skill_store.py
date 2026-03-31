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

import re
from pathlib import Path
from urllib.parse import urlparse

from ..logger import get_logger

logger = get_logger(__name__)

_DEFAULT_SKILLS_DIR = ".agents/skills"


def _domain_to_dirname(domain: str) -> str:
    """将域名转换为安全的目录名。"""
    return re.sub(r"[^a-zA-Z0-9._-]", "_", domain)


def _extract_domain(url: str) -> str:
    """从 URL 中提取域名。"""
    try:
        parsed = urlparse(url)
        return parsed.netloc or parsed.path.split("/")[0]
    except Exception:
        return ""


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

    def save(self, domain: str, content: str) -> Path:
        """保存标准 SKILL.md 文件。

        Args:
            domain: 站点域名（用作目录名）。
            content: 完整的 SKILL.md 内容（含 YAML frontmatter）。

        Returns:
            保存的文件路径。
        """
        dirname = _domain_to_dirname(domain)
        skill_dir = self.skills_dir / dirname
        skill_dir.mkdir(parents=True, exist_ok=True)
        filepath = skill_dir / "SKILL.md"

        temp_path = filepath.with_suffix(".md.tmp")
        temp_path.write_text(content, encoding="utf-8")
        temp_path.replace(filepath)

        logger.info("[SkillStore] Skill 已保存: %s", filepath)
        return filepath

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

    def find_by_url(self, url: str) -> str | None:
        """按 URL 查找匹配的 Skill（通过域名匹配）。

        Returns:
            SKILL.md 的完整文本内容，或 None。
        """
        domain = _extract_domain(url)
        if not domain:
            return None
        return self.load(domain)

    def list_all(self) -> list[str]:
        """列出所有已存储的 Skill 域名。"""
        domains: list[str] = []
        for child in sorted(self.skills_dir.iterdir()):
            if child.is_dir() and (child / "SKILL.md").exists():
                domains.append(child.name)
        return domains

    def _find_project_root(self) -> Path:
        """向上查找项目根目录（含 pyproject.toml 或 .git 的目录）。"""
        current = Path(__file__).resolve()
        for parent in current.parents:
            if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
                return parent
        return Path.cwd()
