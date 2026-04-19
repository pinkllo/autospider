from __future__ import annotations

from pathlib import Path


def domain_to_dirname(domain: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in domain)


def skill_document_path(skills_dir: Path, domain: str) -> Path:
    return skills_dir / domain_to_dirname(domain) / "SKILL.md"
