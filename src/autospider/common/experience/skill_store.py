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

from dataclasses import dataclass
import re
from pathlib import Path
from urllib.parse import urlparse

import yaml

from ..logger import get_logger

logger = get_logger(__name__)

_DEFAULT_SKILLS_DIR = ".agents/skills"


@dataclass(frozen=True)
class SkillMetadata:
    """供 LLM 暴露的 Skill 元信息。"""

    name: str
    description: str
    path: str
    domain: str


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


def _parse_frontmatter(content: str) -> dict[str, str]:
    """提取 SKILL.md frontmatter 中的 name/description。"""
    text = str(content or "")
    if not text.startswith("---"):
        return {}

    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}

    try:
        data = yaml.safe_load(parts[1]) or {}
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
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
