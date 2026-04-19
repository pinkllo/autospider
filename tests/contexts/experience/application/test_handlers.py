from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from autospider.contexts.experience.application.dto import (
    SedimentSkillInput,
    SedimentSkillResultDTO,
    SkillDocumentDTO,
    SkillRuleDataDTO,
)
from autospider.contexts.experience.application.handlers import (
    CollectionFinalizedHandler,
    CollectionFinalizedPayload,
    ExperienceHandlers,
    SedimentSkillFieldPayload,
    SedimentSkillPayload,
)
from autospider.contexts.experience.application.skill_promotion import SkillSedimentationPayload
from autospider.platform.shared_kernel.result import ResultEnvelope


class FakeSedimentSkill:
    def __init__(self) -> None:
        self.received: SedimentSkillInput | None = None

    async def run(self, command: SedimentSkillInput) -> ResultEnvelope[SedimentSkillResultDTO]:
        self.received = command
        result = SedimentSkillResultDTO(
            path="skills/example.com/SKILL.md",
            document=SkillDocumentDTO(
                frontmatter={},
                title="# example.com 采集指南",
                rules=SkillRuleDataDTO(),
            ),
        )
        return ResultEnvelope.success(data=result, trace_id="trace-handler")


class FakePromotionSedimenter:
    def __init__(self) -> None:
        self.received: SkillSedimentationPayload | None = None

    def sediment_from_pipeline_result(self, payload: SkillSedimentationPayload) -> Path | None:
        self.received = payload
        return Path("skills/example.com/SKILL.md")


def _make_artifacts_dir() -> Path:
    artifacts_dir = Path("D:/autospider/.tmp/experience_handler_tests") / uuid4().hex
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    return artifacts_dir


@pytest.mark.asyncio
async def test_handlers_map_payload_to_sediment_use_case() -> None:
    fake_use_case = FakeSedimentSkill()
    handlers = ExperienceHandlers(fake_use_case)
    payload = SedimentSkillPayload(
        domain="example.com",
        name="example.com 站点采集",
        description="示例技能",
        list_url="https://example.com/list",
        task_description="抓取商品信息",
        fields=[
            SedimentSkillFieldPayload(
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

    result = await handlers.handle_sediment_skill(payload)

    assert result.status == "success"
    assert result.data is not None
    assert result.data.path == "skills/example.com/SKILL.md"
    assert fake_use_case.received is not None
    assert fake_use_case.received.domain == "example.com"
    assert fake_use_case.received.fields[0].name == "title"
    assert fake_use_case.received.overwrite_existing is True


def test_collection_finalized_handler_loads_pipeline_summary() -> None:
    artifacts_dir = _make_artifacts_dir()
    (artifacts_dir / "pipeline_summary.json").write_text(
        json.dumps(
            {
                "list_url": "https://example.com/list",
                "task_description": "抓取商品信息",
                "anchor_url": "https://example.com/list?page=1",
                "page_state_signature": "sig-1",
                "variant_label": "default",
                "execution_brief": {"category": "books", "page": 1},
                "collection_config": {"detail_xpath": "//a[@class='detail']"},
                "extraction_config": {"fields": [{"name": "title", "xpath": "//h1/text()"}]},
                "extraction_evidence": [{"name": "title", "xpath": "//h1/text()"}],
                "validation_failures": [],
                "plan_knowledge": "经验摘要",
                "success_count": 8,
                "total_urls": 10,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    sedimenter = FakePromotionSedimenter()

    promoted = CollectionFinalizedHandler(sedimenter).handle(
        CollectionFinalizedPayload(artifacts_dir=str(artifacts_dir))
    )

    assert promoted == Path("skills/example.com/SKILL.md")
    assert sedimenter.received is not None
    assert sedimenter.received.list_url == "https://example.com/list"
    assert sedimenter.received.summary["success_count"] == 8
    assert sedimenter.received.promotion_context.context == {"category": "books", "page": "1"}


def test_collection_finalized_handler_rejects_invalid_summary() -> None:
    artifacts_dir = _make_artifacts_dir()
    (artifacts_dir / "pipeline_summary.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="list_url/task_description"):
        CollectionFinalizedHandler(FakePromotionSedimenter()).handle(
            CollectionFinalizedPayload(artifacts_dir=str(artifacts_dir))
        )
