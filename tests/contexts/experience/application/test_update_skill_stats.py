from __future__ import annotations

import pytest

from autospider.contexts.experience.application.dto import (
    SkillDocumentDTO,
    SkillFieldRuleDTO,
    SkillRuleDataDTO,
    UpdateSkillStatsInput,
)
from autospider.contexts.experience.application.use_cases import UpdateSkillStats
from autospider.contexts.experience.domain.services import SkillDocumentService
from autospider.platform.shared_kernel.trace import clear_run_context, set_run_context


@pytest.mark.asyncio
async def test_update_skill_stats_returns_success_envelope() -> None:
    use_case = UpdateSkillStats()
    set_run_context(run_id=None, trace_id="trace-experience-update-stats")
    command = UpdateSkillStatsInput(
        document=_build_document(),
        status="VALIDATED",
        success_rate=1.2,
        success_rate_text="",
    )

    result = await use_case.run(command)

    assert result.status == "success"
    assert result.data is not None
    assert result.data.updated_document.rules.status == "validated"
    assert result.data.updated_document.rules.success_rate == 1.0
    assert result.data.updated_document.rules.success_rate_text == "100%"
    clear_run_context()


@pytest.mark.asyncio
async def test_update_skill_stats_returns_failed_envelope_for_invalid_status() -> None:
    use_case = UpdateSkillStats()
    set_run_context(run_id=None, trace_id="trace-experience-update-stats-invalid")
    command = UpdateSkillStatsInput(
        document=_build_document(),
        status="not-a-status",
        success_rate=0.5,
        success_rate_text="50%",
    )

    result = await use_case.run(command)

    assert result.status == "failed"
    assert result.data is None
    assert result.errors[0].code == "experience.update_stats_failed"
    assert "invalid status" in result.errors[0].message
    clear_run_context()


class RaisingUpdateSkillStatsService(SkillDocumentService):
    def update_skill_stats(
        self,
        *,
        document,
        status: str,
        success_rate: float,
        success_rate_text: str = "",
    ):
        raise RuntimeError("unexpected update failure")


@pytest.mark.asyncio
async def test_update_skill_stats_does_not_swallow_runtime_error() -> None:
    use_case = UpdateSkillStats(service=RaisingUpdateSkillStatsService())
    set_run_context(run_id=None, trace_id="trace-experience-update-stats-runtime")
    command = UpdateSkillStatsInput(
        document=_build_document(),
        status="validated",
        success_rate=0.8,
        success_rate_text="80%",
    )

    with pytest.raises(RuntimeError, match="unexpected update failure"):
        await use_case.run(command)
    clear_run_context()


def _build_document() -> SkillDocumentDTO:
    return SkillDocumentDTO(
        frontmatter={"name": "example.com 站点采集", "description": "示例技能"},
        title="# example.com 采集指南",
        rules=SkillRuleDataDTO(
            domain="example.com",
            name="example.com 站点采集",
            description="示例技能",
            list_url="https://example.com/list",
            task_description="抓取商品信息",
            status="draft",
            success_rate=0.2,
            success_rate_text="20%",
            fields=[
                SkillFieldRuleDTO(
                    name="title",
                    description="标题",
                    primary_xpath="//h1/text()",
                )
            ],
        ),
    )
