from __future__ import annotations

from autospider.contexts.experience.domain.model import SkillMetadata
from autospider.contexts.experience.domain.policies import extract_domain
from autospider.contexts.experience.infrastructure.repositories.skill_index_repository import (
    SkillIndexRepository,
)


class SkillQueryService:
    def __init__(self, index_repository: SkillIndexRepository) -> None:
        self._index_repository = index_repository

    def list_by_url(self, url: str) -> list[SkillMetadata]:
        domain = extract_domain(url)
        if not domain:
            return []
        return self._index_repository.list_by_domain(domain)

    def list_by_domain(self, domain: str) -> list[SkillMetadata]:
        return self._index_repository.list_by_domain(domain)

    def list_all_metadata(self) -> list[SkillMetadata]:
        return self._index_repository.list_all_metadata()
