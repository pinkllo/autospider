from __future__ import annotations

import pytest

from autospider.contexts.experience.domain.model import SkillDocument, SkillFieldRule, SkillRuleData
from autospider.contexts.experience.domain.services import SkillDocumentService


def test_build_skill_document_sets_status_and_success_rate() -> None:
    service = SkillDocumentService()
    fields = {
        "title": SkillFieldRule(
            name="title",
            description="标题",
            primary_xpath="//h1/text()",
            validated=True,
            confidence=0.9,
        )
    }

    document = service.build_skill_document(
        domain="example.com",
        name="example.com 站点采集",
        description="示例技能",
        list_url="https://example.com/list",
        task_description="抓取商品信息",
        fields=fields,
        status="validated",
        success_count=8,
        total_count=10,
    )

    assert document.rules.status == "validated"
    assert document.rules.success_rate == 0.8
    assert document.rules.success_rate_text == "80% (8/10)"
    assert document.frontmatter["name"] == "example.com 站点采集"


def test_merge_skill_documents_keeps_validated_primary_xpath() -> None:
    service = SkillDocumentService()
    existing = _build_document(
        status="validated",
        field=SkillFieldRule(
            name="title",
            primary_xpath="//h1/text()",
            fallback_xpaths=("//h2/text()",),
            validated=True,
            confidence=0.9,
        ),
    )
    incoming = _build_document(
        status="unstable",
        field=SkillFieldRule(
            name="title",
            primary_xpath="//div[@class='title']/text()",
            fallback_xpaths=("//header/h1/text()",),
            validated=False,
            confidence=0.5,
        ),
    )

    merged = service.merge_skill_documents(existing=existing, incoming=incoming)

    merged_field = merged.rules.fields["title"]
    assert merged_field.primary_xpath == "//h1/text()"
    assert merged_field.validated is True
    assert "//div[@class='title']/text()" in merged_field.fallback_xpaths


def test_update_skill_stats_normalizes_status_and_rate() -> None:
    service = SkillDocumentService()
    original = _build_document(
        status="draft",
        field=SkillFieldRule(name="title", primary_xpath="//h1/text()"),
    )

    updated = service.update_skill_stats(
        document=original,
        status="VALIDATED",
        success_rate=1.4,
        success_rate_text="",
    )

    assert updated.rules.status == "validated"
    assert updated.rules.success_rate == 1.0
    assert updated.rules.success_rate_text == "100%"


def test_build_skill_document_rejects_invalid_status() -> None:
    service = SkillDocumentService()

    with pytest.raises(ValueError, match="invalid status"):
        service.build_skill_document(
            domain="example.com",
            name="example.com 站点采集",
            description="示例技能",
            list_url="https://example.com/list",
            task_description="抓取商品信息",
            fields={},
            status="unknown",
        )


def _build_document(*, status: str, field: SkillFieldRule) -> SkillDocument:
    return SkillDocument(
        frontmatter={"name": "example.com 站点采集", "description": "示例技能"},
        title="# example.com 采集指南",
        rules=SkillRuleData(
            domain="example.com",
            name="example.com 站点采集",
            description="示例技能",
            list_url="https://example.com/list",
            task_description="抓取商品信息",
            status=status,
            fields={"title": field},
        ),
    )
