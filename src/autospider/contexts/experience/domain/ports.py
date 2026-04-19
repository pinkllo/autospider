from __future__ import annotations

from typing import Protocol

from autospider.contexts.experience.domain.model import SkillDocument, SkillMetadata


class SkillRepository(Protocol):
    def save_document(
        self,
        domain: str,
        document: SkillDocument,
        *,
        overwrite_existing: bool = False,
    ) -> str: ...

    def load_by_path(self, path: str) -> str: ...

    def list_by_url(self, url: str) -> list[SkillMetadata]: ...

    def list_by_domain(self, domain: str) -> list[SkillMetadata]: ...

    def list_all_metadata(self) -> list[SkillMetadata]: ...

    def is_llm_eligible_path(self, path: str) -> bool: ...
