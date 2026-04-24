from __future__ import annotations

from autospider.platform.shared_kernel.knowledge_contracts import (
    DetailFieldProfile,
    ListPageProfile,
    VisualDecisionHint,
    build_list_profile_key,
    coerce_detail_field_profile,
    coerce_list_page_profile,
    coerce_visual_decision_hint,
)


def test_list_page_profile_round_trip_supports_legacy_aliases() -> None:
    profile = coerce_list_page_profile(
        {
            "list_url": "https://example.com/list",
            "anchor_url": "https://example.com",
            "page_state_signature": "sig-list",
            "variant_label": "采购公告",
            "task_description": "采集详情链接",
            "nav_steps": [{"action": "click", "target_text": "采购公告"}],
            "detail_xpath": "//a[@class='detail']",
            "pagination_xpath": "//a[@rel='next']",
            "jump_input_selector": "//input[@type='number']",
            "jump_button_selector": "//button[@type='submit']",
            "validated_at": "2026-04-24T12:00:00+08:00",
            "source": "runtime_cache",
            "confidence": 0.9,
        }
    )

    payload = profile.to_payload()
    round_trip = ListPageProfile.from_mapping(payload)

    assert profile.common_detail_xpath == "//a[@class='detail']"
    assert profile.jump_widget_xpath.input_xpath == "//input[@type='number']"
    assert payload["jump_widget_xpath"] == {
        "input": "//input[@type='number']",
        "button": "//button[@type='submit']",
    }
    assert round_trip == profile


def test_detail_field_profile_round_trip_supports_legacy_xpath_aliases() -> None:
    profile = coerce_detail_field_profile(
        {
            "domain": "example.com",
            "template_signature": "detail-v1",
            "name": "title",
            "primary_xpath": "//h1/text()",
            "fallback_xpaths": ["//meta[@property='og:title']/@content"],
            "extraction_source": "skill",
            "validated": "true",
            "success_count": "3",
            "failure_count": "1",
        }
    )

    payload = profile.to_payload()
    round_trip = DetailFieldProfile.from_mapping(payload)

    assert profile.field_signature == "title"
    assert profile.xpath == "//h1/text()"
    assert payload["xpath_fallbacks"] == ["//meta[@property='og:title']/@content"]
    assert round_trip == profile


def test_visual_decision_hint_round_trip_defaults_missing_values_to_empty_strings() -> None:
    profile = coerce_visual_decision_hint({"purpose": "paginate", "xpath": "//a[@rel='next']"})

    payload = profile.to_payload()
    round_trip = VisualDecisionHint.from_mapping(payload)
    empty_profile = coerce_visual_decision_hint({})

    assert profile.resolved_xpath == "//a[@rel='next']"
    assert round_trip == profile
    assert empty_profile.target_text == ""
    assert empty_profile.last_mark_text == ""
    assert empty_profile.ttl_scope == ""


def test_build_list_profile_key_separates_variant_labels() -> None:
    left = build_list_profile_key(
        page_state_signature="sig-list",
        anchor_url="https://example.com/root",
        variant_label="采购公告",
        task_description="采集详情链接",
    )
    right = build_list_profile_key(
        page_state_signature="sig-list",
        anchor_url="https://example.com/root",
        variant_label="中标公告",
        task_description="采集详情链接",
    )

    assert left != right
