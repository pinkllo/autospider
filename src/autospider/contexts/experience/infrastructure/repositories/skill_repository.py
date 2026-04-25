from __future__ import annotations

from pathlib import Path

from autospider.contexts.experience.domain.model import SkillDocument, SkillMetadata
from autospider.contexts.experience.domain.services import SkillDocumentService
from autospider.contexts.experience.infrastructure.repositories.skill_document_codec import (
    parse_skill_document,
    render_skill_document,
    skill_document_path,
)
from autospider.contexts.experience.infrastructure.repositories.skill_index_repository import (
    SkillIndexRepository,
)
from autospider.contexts.experience.infrastructure.repositories.skill_query_service import (
    SkillQueryService,
)

_DEFAULT_SKILLS_DIR = "skills"


def merge_skill_documents(existing: SkillDocument, incoming: SkillDocument) -> SkillDocument:
    service = SkillDocumentService()
    return service.merge_skill_documents(existing=existing, incoming=incoming)


class SkillRepository:
    def __init__(self, skills_dir: str | Path | None = None) -> None:
        self.skills_dir = Path(skills_dir or _DEFAULT_SKILLS_DIR)
        self._index_repository = SkillIndexRepository(self.skills_dir)
        self._query_service = SkillQueryService(self._index_repository)

    def save_document(self, domain: str, document, *, overwrite_existing: bool = False) -> str:
        path = skill_document_path(self.skills_dir, domain)
        path.parent.mkdir(parents=True, exist_ok=True)
        final_document = document
        if path.exists() and not overwrite_existing:
            existing = parse_skill_document(path.read_text(encoding="utf-8"))
            final_document = merge_skill_documents(existing, document)
        path.write_text(render_skill_document(final_document), encoding="utf-8")
        return str(path)

    def save_markdown(
        self,
        domain: str,
        content: str,
        *,
        overwrite_existing: bool = True,
    ) -> str:
        path = skill_document_path(self.skills_dir, domain)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and not overwrite_existing:
            raise FileExistsError(f"skill already exists: {path}")
        path.write_text(str(content or "").strip() + "\n", encoding="utf-8")
        return str(path)

    def load_by_path(self, path: str) -> str:
        candidate = Path(path)
        if not candidate.exists():
            return ""
        return candidate.read_text(encoding="utf-8")

    def is_llm_eligible_path(self, path: str) -> bool:
        return self._index_repository.is_llm_eligible_path(path)

    def list_by_url(self, url: str) -> list[SkillMetadata]:
        return self._query_service.list_by_url(url)

    def list_by_domain(self, domain: str) -> list[SkillMetadata]:
        return self._query_service.list_by_domain(domain)

    def list_all_metadata(self) -> list[SkillMetadata]:
        return self._query_service.list_all_metadata()
