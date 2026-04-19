from __future__ import annotations

from pathlib import Path

from autospider.contexts.experience.domain.model import SkillMetadata
from autospider.contexts.experience.domain.policies import normalize_host
from autospider.contexts.experience.infrastructure.repositories.parsing import parse_skill_document
from autospider.contexts.experience.infrastructure.repositories.pathing import (
    domain_to_dirname,
    skill_document_path,
)


class SkillIndexRepository:
    def __init__(self, skills_dir: str | Path) -> None:
        self._skills_dir = Path(skills_dir)

    def list_by_domain(self, domain: str) -> list[SkillMetadata]:
        normalized_domain = normalize_host(domain)
        if not normalized_domain:
            return []
        skill_file = skill_document_path(self._skills_dir, normalized_domain)
        loaded = self._load_metadata(skill_file=skill_file, fallback_domain=normalized_domain)
        if loaded is None:
            return []
        return [loaded]

    def list_all_metadata(self) -> list[SkillMetadata]:
        metadata: list[SkillMetadata] = []
        if not self._skills_dir.exists():
            return metadata
        for child in self._skills_dir.iterdir():
            skill_file = child / "SKILL.md"
            loaded = self._load_metadata(skill_file=skill_file, fallback_domain=child.name)
            if loaded is not None:
                metadata.append(loaded)
        return metadata

    def is_llm_eligible_path(self, path: str) -> bool:
        parts = [part.lower() for part in Path(path).parts]
        for index, part in enumerate(parts):
            if part == "output" and index + 1 < len(parts) and parts[index + 1] == "draft_skills":
                return False
        return True

    def _load_metadata(self, *, skill_file: Path, fallback_domain: str) -> SkillMetadata | None:
        if not skill_file.exists():
            return None
        if not self.is_llm_eligible_path(str(skill_file)):
            return None
        document = parse_skill_document(skill_file.read_text(encoding="utf-8"))
        if not document.rules.name or not document.rules.description:
            return None
        domain = normalize_host(document.rules.domain) or normalize_host(fallback_domain)
        return SkillMetadata(
            name=document.rules.name,
            description=document.rules.description,
            path=str(skill_file),
            domain=domain or domain_to_dirname(fallback_domain),
        )
