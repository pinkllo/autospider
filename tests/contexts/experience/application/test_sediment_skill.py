from __future__ import annotations

import pytest

from autospider.contexts.experience.application.dto import SedimentSkillInput
from autospider.contexts.experience.application.use_cases import SedimentSkill
from autospider.contexts.experience.domain.model import SkillDocument, SkillFieldRule
from autospider.platform.shared_kernel.trace import clear_run_context, set_run_context


class InMemorySkillRepository:
    def __init__(self) -> None:
        self.saved_domain = ""
        self.saved_document: SkillDocument | None = None
        self.saved_overwrite_existing = False

    def save_document(
        self,
        domain: str,
        document: SkillDocument,
        *,
        overwrite_existing: bool = False,
    ) -> str:
        self.saved_domain = domain
        self.saved_document = document
        self.saved_overwrite_existing = overwrite_existing
        return "skills/example.com/SKILL.md"


class RaisingSkillRepository:
    def save_document(
        self,
        domain: str,
        document: SkillDocument,
        *,
        overwrite_existing: bool = False,
    ) -> str:
        raise RuntimeError("repository is unavailable")


@pytest.mark.asyncio
async def test_sediment_skill_persists_document_and_returns_success_envelope() -> None:
    repository = InMemorySkillRepository()
    use_case = SedimentSkill(repository)
    set_run_context(run_id=None, trace_id="trace-experience-sediment")

    result = await use_case.run(
        SedimentSkillInput(
            domain="example.com",
            name="example.com 站点采集",
            description="示例技能",
            list_url="https://example.com/list",
            task_description="抓取商品信息",
            fields=[
                SkillFieldRule(
                    name="title",
                    description="标题",
                    primary_xpath="//h1/text()",
                    validated=True,
                    confidence=0.9,
                )
            ],
            status="validated",
            success_count=8,
            total_count=10,
            overwrite_existing=True,
        )
    )

    assert result.status == "success"
    assert result.data is not None
    assert result.data.path == "skills/example.com/SKILL.md"
    assert repository.saved_domain == "example.com"
    assert repository.saved_overwrite_existing is True
    assert repository.saved_document is not None
    assert repository.saved_document.rules.name == "example.com 站点采集"
    clear_run_context()


@pytest.mark.asyncio
async def test_sediment_skill_returns_failed_envelope_for_input_error() -> None:
    repository = InMemorySkillRepository()
    use_case = SedimentSkill(repository)
    set_run_context(run_id=None, trace_id="trace-experience-sediment-failed")

    result = await use_case.run(
        SedimentSkillInput(
            domain="example.com",
            name="example.com 站点采集",
            description="示例技能",
            list_url="https://example.com/list",
            task_description="抓取商品信息",
            status="invalid-status",
        )
    )

    assert result.status == "failed"
    assert result.errors[0].code == "experience.sediment_failed"
    assert "invalid status" in result.errors[0].message
    clear_run_context()


@pytest.mark.asyncio
async def test_sediment_skill_does_not_swallow_runtime_error() -> None:
    use_case = SedimentSkill(RaisingSkillRepository())
    set_run_context(run_id=None, trace_id="trace-experience-sediment-runtime")

    with pytest.raises(RuntimeError, match="repository is unavailable"):
        await use_case.run(
            SedimentSkillInput(
                domain="example.com",
                name="example.com 站点采集",
                description="示例技能",
                list_url="https://example.com/list",
                task_description="抓取商品信息",
                status="validated",
            )
        )
    clear_run_context()
