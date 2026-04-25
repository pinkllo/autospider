from __future__ import annotations

from autospider.contexts.experience.application.skill_promotion import (
    SkillSedimentationPayload,
    SkillSedimenter,
)


class InMemoryGuideRepository:
    def __init__(self) -> None:
        self.saved_domain = ""
        self.saved_content = ""
        self.saved_overwrite_existing = False

    def save_markdown(
        self,
        domain: str,
        content: str,
        *,
        overwrite_existing: bool = True,
    ) -> str:
        self.saved_domain = domain
        self.saved_content = content
        self.saved_overwrite_existing = overwrite_existing
        return f"skills/{domain}/SKILL.md"


def test_pipeline_sedimenter_writes_lightweight_guide() -> None:
    repository = InMemoryGuideRepository()
    sedimenter = SkillSedimenter(repository)

    path = sedimenter.sediment_from_pipeline_result(
        SkillSedimentationPayload(
            list_url="https://ygp.gdzwfw.gov.cn/#/44/jygg",
            task_description="按相关分类采集招标项目名称和分类类别",
            fields=[],
            collection_config={
                "common_detail_xpath": "//*[@id='app']/main/div[3]/table/tbody/tr[1]/td/span",
            },
            extraction_config={
                "fields": [
                    {
                        "name": "category_name",
                        "extraction_source": "subtask_context",
                        "fixed_value": "水利工程",
                    },
                    {
                        "name": "project_name",
                        "xpath": "//*[@id='app']/main/div[3]/table/tbody/tr[1]/td/span",
                    },
                ],
            },
            summary={"success_count": 9, "total_urls": 9},
            subtask_names=["全部", "房屋建筑和市政基础设施工程", "水利工程"],
            plan_knowledge="左侧有业务领域导航，顶部有相关分类筛选。",
        )
    )

    assert path is not None
    assert path.as_posix() == "skills/ygp.gdzwfw.gov.cn/SKILL.md"
    assert repository.saved_domain == "ygp.gdzwfw.gov.cn"
    assert repository.saved_overwrite_existing is True
    assert "## 适用范围" in repository.saved_content
    assert "## 页面特征" in repository.saved_content
    assert "## 采集策略" in repository.saved_content
    assert "## 字段提示" in repository.saved_content
    assert "## 避免事项" in repository.saved_content
    assert "## 字段提取规则" not in repository.saved_content
    assert "`category_name` 优先从当前子任务、分类或任务上下文继承。" in repository.saved_content
    assert "不要把只命中首行" in repository.saved_content


def test_pipeline_sedimenter_skips_when_no_successful_items() -> None:
    repository = InMemoryGuideRepository()
    sedimenter = SkillSedimenter(repository)

    path = sedimenter.sediment_from_pipeline_result(
        SkillSedimentationPayload(
            list_url="https://example.com/list",
            task_description="采集商品",
            fields=[],
            extraction_config={"fields": [{"name": "title", "xpath": "//h1"}]},
            summary={"success_count": 0, "total_urls": 3},
        )
    )

    assert path is None
    assert repository.saved_content == ""
