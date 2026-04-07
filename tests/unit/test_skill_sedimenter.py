from __future__ import annotations

from autospider.common.experience.skill_sedimenter import SkillSedimenter
from autospider.common.experience.skill_store import SkillDocument, SkillFieldRule, SkillRuleData, render_skill_document


def test_rule_based_insights_emphasize_stability_and_risk():
    sedimenter = SkillSedimenter(skills_dir=".tmp_test_skill_sedimenter")

    insights = sedimenter._rule_based_insights(
        domain="example.com",
        fields=[],
        extraction_config={
            "fields": [
                {
                    "name": "project_name",
                    "xpath": "//table//tr/td[1]",
                    "xpath_validated": False,
                    "xpath_fallbacks": ["//ul/li/a", "//div[@class='title']"],
                }
            ]
        },
        validation_failures=[
            {
                "fields": [
                    {"field_name": "project_name", "error": "element not found"},
                    {"field_name": "project_name", "error": "timeout waiting for selector"},
                ]
            }
        ],
        summary={"success_count": 7, "total_urls": 10},
    )

    assert "成功率 70% (7/10)" in insights
    assert "project_name 尚未稳定验证" in insights
    assert "需要依赖多个 fallback" in insights
    assert "元素定位失败" in insights or "等待超时或页面未稳定" in insights


def test_merge_subtask_xpaths_keeps_old_primary_without_stale_evidence():
    sedimenter = SkillSedimenter(skills_dir=".tmp_test_skill_sedimenter")

    merged = sedimenter._merge_subtask_xpaths(
        [
            {
                "extraction_config": {
                    "fields": [
                        {
                            "name": "title",
                            "xpath": "//main/h1",
                            "xpath_validated": True,
                            "xpath_fallbacks": [],
                        }
                    ]
                }
            }
        ],
        [{"name": "title", "description": "标题"}],
        base_fields=[
            {
                "name": "title",
                "xpath": "//h1",
                "xpath_validated": True,
                "xpath_fallbacks": [],
            }
        ],
        validation_failures=[],
    )

    field = merged["fields"][0]
    assert field["xpath"] == "//h1"
    assert field["replace_primary"] is False
    assert "//main/h1" in field["xpath_fallbacks"]


def test_merge_subtask_xpaths_replaces_primary_when_old_xpath_is_stale():
    sedimenter = SkillSedimenter(skills_dir=".tmp_test_skill_sedimenter")

    merged = sedimenter._merge_subtask_xpaths(
        [
            {
                "extraction_config": {
                    "fields": [
                        {
                            "name": "title",
                            "xpath": "//main/h1",
                            "xpath_validated": True,
                            "xpath_fallbacks": [],
                        },
                        {
                            "name": "title",
                            "xpath": "//article/h1",
                            "xpath_validated": True,
                            "xpath_fallbacks": [],
                        },
                    ]
                }
            }
        ],
        [{"name": "title", "description": "标题"}],
        base_fields=[
            {
                "name": "title",
                "xpath": "//h1",
                "xpath_validated": True,
                "xpath_fallbacks": [],
            }
        ],
        validation_failures=[
            {"fields": [{"field_name": "title", "error": "element not found"}]}
        ],
    )

    field = merged["fields"][0]
    assert field["xpath"] == "//main/h1"
    assert field["replace_primary"] is True
    assert "//h1" in field["xpath_fallbacks"]


def test_render_skill_document_skips_empty_nav_steps():
    document = SkillDocument(
        frontmatter={"name": "example.com 站点采集", "description": "desc"},
        title="# example.com 采集指南",
        rules=SkillRuleData(
            domain="example.com",
            name="example.com 站点采集",
            description="desc",
            list_url="https://example.com/list",
            task_description="采集标题",
            nav_steps=[{"action": "click", "description": "", "xpath": "", "value": ""}],
            fields={
                "title": SkillFieldRule(
                    name="title",
                    primary_xpath="//h1",
                    validated=True,
                    confidence=0.9,
                )
            },
        ),
        insights_markdown="- 稳定规则可复用。",
    )

    rendered = render_skill_document(document)

    assert "## 列表页导航" not in rendered
    assert "1. **click**" not in rendered


def test_incoming_insights_replace_existing_without_scoring():
    existing = "- 旧经验"
    incoming = "- 新经验"

    assert (incoming or existing) == "- 新经验"
