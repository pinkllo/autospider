from __future__ import annotations

import pytest

from autospider.contexts.experience.application.dto import LookupSkillInput
from autospider.contexts.experience.application.use_cases import LookupSkill
from autospider.contexts.experience.domain.model import SkillMetadata
from autospider.platform.shared_kernel.trace import clear_run_context, set_run_context


class InMemorySkillRepository:
    def __init__(self) -> None:
        self._items = [
            SkillMetadata(
                name="example.com 站点采集",
                description="示例技能",
                path="skills/example.com/SKILL.md",
                domain="example.com",
            )
        ]

    def list_by_url(self, url: str) -> list[SkillMetadata]:
        if "example.com" not in url:
            return []
        return list(self._items)


@pytest.mark.asyncio
async def test_lookup_skill_returns_matching_metadata() -> None:
    set_run_context(run_id=None, trace_id="trace-experience-lookup")
    use_case = LookupSkill(InMemorySkillRepository())

    result = await use_case.run(LookupSkillInput(url="https://example.com/list"))

    assert result.status == "success"
    assert result.data is not None
    assert result.data.matches[0].domain == "example.com"
    clear_run_context()
