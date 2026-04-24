from __future__ import annotations

from autospider.contexts.experience.domain.model import (
    SkillFieldRule,
    SkillRuleData,
    SkillVariantRule,
)


def test_skill_models_bridge_to_reusable_knowledge_contracts() -> None:
    rule_data = SkillRuleData(
        domain="example.com",
        list_url="https://example.com/list",
        task_description="采集详情链接",
        success_rate=0.8,
        detail_xpath="//a[@class='detail']",
        pagination_xpath="//a[@rel='next']",
        jump_input_selector="//input[@type='number']",
        jump_button_selector="//button[@type='submit']",
        nav_steps=({"action": "click", "target_text": "采购公告"},),
        fields={
            "title": SkillFieldRule(
                name="title",
                extraction_source="xpath",
                primary_xpath="//h1/text()",
                fallback_xpaths=("//meta[@property='og:title']/@content",),
                validated=True,
            )
        },
    )

    list_profile = rule_data.to_list_page_profile()
    detail_profiles = rule_data.to_detail_field_profiles(detail_template_signature="detail-v1")
    variant = SkillVariantRule.from_list_page_profile(list_profile)
    field_rule = SkillFieldRule.from_detail_field_profile(detail_profiles[0])

    assert list_profile.common_detail_xpath == "//a[@class='detail']"
    assert list_profile.jump_widget_xpath.input_xpath == "//input[@type='number']"
    assert detail_profiles[0].field_name == "title"
    assert detail_profiles[0].xpath == "//h1/text()"
    assert variant.detail_xpath == "//a[@class='detail']"
    assert field_rule.primary_xpath == "//h1/text()"
