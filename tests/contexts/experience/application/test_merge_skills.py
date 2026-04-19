from __future__ import annotations

import pytest

from autospider.contexts.experience.application.dto import (
    MergeSkillsInput,
    SkillDocumentDTO,
    SkillFieldRuleDTO,
    SkillRuleDataDTO,
)
from autospider.contexts.experience.application.use_cases import MergeSkills
from autospider.contexts.experience.domain.services import SkillDocumentService
from autospider.platform.shared_kernel.trace import clear_run_context, set_run_context


@pytest.mark.asyncio
async def test_merge_skills_returns_success_and_keeps_validated_primary_xpath() -> None:
    use_case = MergeSkills()
    set_run_context(run_id=None, trace_id="trace-experience-merge")
    existing = _build_document(
        status="validated",
        primary_xpath="//h1/text()",
        fallback_xpaths=["//h2/text()"],
        validated=True,
        confidence=0.9,
    )
    incoming = _build_document(
        status="unstable",
        primary_xpath="//div[@class='title']/text()",
        fallback_xpaths=["//header/h1/text()"],
        validated=False,
        confidence=0.5,
    )

    result = await use_case.run(
        MergeSkillsInput(
            existing_document=existing,
            incoming_document=incoming,
        )
    )

    assert result.status == "success"
    assert result.data is not None
    merged_field = result.data.merged_document.rules.fields[0]
    assert merged_field.primary_xpath == "//h1/text()"
    assert merged_field.validated is True
    assert "//div[@class='title']/text()" in merged_field.fallback_xpaths
    clear_run_context()


@pytest.mark.asyncio
async def test_merge_skills_returns_failed_envelope_for_input_error() -> None:
    use_case = MergeSkills()
    set_run_context(run_id=None, trace_id="trace-experience-merge-failed")
    existing = _build_document(
        status="validated",
        primary_xpath="//h1/text()",
        fallback_xpaths=[],
        validated=True,
        confidence=0.9,
    )
    incoming = _build_document(
        status="unknown",
        primary_xpath="//h1/text()",
        fallback_xpaths=[],
        validated=True,
        confidence=0.9,
    )

    result = await use_case.run(
        MergeSkillsInput(
            existing_document=existing,
            incoming_document=incoming,
        )
    )

    assert result.status == "failed"
    assert result.errors[0].code == "experience.merge_failed"
    assert "invalid status" in result.errors[0].message
    clear_run_context()


class RaisingMergeService(SkillDocumentService):
    def merge_skill_documents(
        self,
        *,
        existing,
        incoming,
    ):
        raise RuntimeError("unexpected merge failure")


@pytest.mark.asyncio
async def test_merge_skills_does_not_swallow_runtime_error() -> None:
    use_case = MergeSkills(service=RaisingMergeService())
    set_run_context(run_id=None, trace_id="trace-experience-merge-runtime")

    with pytest.raises(RuntimeError, match="unexpected merge failure"):
        await use_case.run(
            MergeSkillsInput(
                existing_document=_build_document(
                    status="validated",
                    primary_xpath="//h1/text()",
                    fallback_xpaths=[],
                    validated=True,
                    confidence=0.9,
                ),
                incoming_document=_build_document(
                    status="validated",
                    primary_xpath="//h1/text()",
                    fallback_xpaths=[],
                    validated=True,
                    confidence=0.9,
                ),
            )
        )
    clear_run_context()


def _build_document(
    *,
    status: str,
    primary_xpath: str,
    fallback_xpaths: list[str],
    validated: bool,
    confidence: float,
) -> SkillDocumentDTO:
    return SkillDocumentDTO(
        frontmatter={"name": "example.com 站点采集", "description": "示例技能"},
        title="# example.com 采集指南",
        rules=SkillRuleDataDTO(
            domain="example.com",
            name="example.com 站点采集",
            description="示例技能",
            list_url="https://example.com/list",
            task_description="抓取商品信息",
            status=status,
            fields=[
                SkillFieldRuleDTO(
                    name="title",
                    description="标题",
                    primary_xpath=primary_xpath,
                    fallback_xpaths=fallback_xpaths,
                    validated=validated,
                    confidence=confidence,
                )
            ],
        ),
    )
