from __future__ import annotations

from autospider.contexts.experience.domain.model import SkillDocument
from autospider.contexts.experience.domain.services import SkillDocumentService


def merge_skill_documents(existing: SkillDocument, incoming: SkillDocument) -> SkillDocument:
    service = SkillDocumentService()
    return service.merge_skill_documents(existing=existing, incoming=incoming)
