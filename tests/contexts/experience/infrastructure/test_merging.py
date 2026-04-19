from __future__ import annotations

from autospider.contexts.experience.domain.model import SkillDocument, SkillRuleData
from autospider.contexts.experience.domain.services import SkillDocumentService
from autospider.contexts.experience.infrastructure.repositories import merging


def test_infra_merge_skill_documents_delegates_to_domain_service(monkeypatch) -> None:
    existing = _build_document(status="validated")
    incoming = _build_document(status="unstable")
    called = {"value": False}

    def _fake_merge(self, *, existing: SkillDocument, incoming: SkillDocument) -> SkillDocument:
        called["value"] = True
        return incoming

    monkeypatch.setattr(SkillDocumentService, "merge_skill_documents", _fake_merge)

    merged = merging.merge_skill_documents(existing, incoming)

    assert called["value"] is True
    assert merged is incoming


def _build_document(*, status: str) -> SkillDocument:
    return SkillDocument(
        frontmatter={},
        title="# example.com 采集指南",
        rules=SkillRuleData(
            domain="example.com",
            name="example.com 站点采集",
            description="示例技能",
            status=status,
        ),
    )
