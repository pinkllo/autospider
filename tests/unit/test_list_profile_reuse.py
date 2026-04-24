from __future__ import annotations

from types import SimpleNamespace

import pytest

from autospider.contexts.collection.application.use_cases.collect_urls import URLCollector
from autospider.contexts.collection.infrastructure.repositories.config_repository import CollectionConfig
from autospider.contexts.experience.application.skill_promotion import (
    SkillPromotionContext,
    SkillSedimentationPayload,
    _build_candidate,
    _build_document,
)


def test_skill_promotion_maps_common_detail_xpath_to_skill_rule() -> None:
    payload = SkillSedimentationPayload(
        list_url="https://example.com/list",
        task_description="collect items",
        fields=[],
        collection_config={"common_detail_xpath": "//a[@class='item']"},
        extraction_config={"fields": [{"name": "title", "xpath": "//h1"}]},
        summary={"success_count": 2, "total_urls": 2},
        promotion_context=SkillPromotionContext(),
    )

    candidate = _build_candidate(payload)
    assert candidate is not None
    document = _build_document(candidate)

    assert document.rules.detail_xpath == "//a[@class='item']"


def test_collection_config_accepts_legacy_detail_xpath_alias() -> None:
    config = CollectionConfig.from_mapping(
        {
            "detail_xpath": "//a[@class='legacy']",
            "jump_input_selector": "//input[@name='page']",
            "jump_button_selector": "//button[text()='Go']",
        }
    )

    assert config.common_detail_xpath == "//a[@class='legacy']"
    assert config.jump_widget_xpath == {
        "input": "//input[@name='page']",
        "button": "//button[text()='Go']",
    }


@pytest.mark.asyncio
async def test_url_collector_rejects_empty_initial_profile() -> None:
    collector = URLCollector.__new__(URLCollector)
    collector.initial_collection_config = CollectionConfig(common_detail_xpath="")
    collector.initial_collection_config_candidates = [collector.initial_collection_config]

    assert await URLCollector._try_apply_initial_collection_config(collector) is False


@pytest.mark.asyncio
async def test_url_collector_rejects_profile_without_preview_hits() -> None:
    collector = URLCollector.__new__(URLCollector)
    collector.initial_collection_config = CollectionConfig(common_detail_xpath="//a")
    collector.initial_collection_config_candidates = [collector.initial_collection_config]
    collector.common_detail_xpath = None
    collector.nav_steps = []
    collector.pagination_handler = None
    collector.navigation_handler = SimpleNamespace()

    async def preview_urls() -> list[str]:
        return []

    collector._preview_urls_with_xpath = preview_urls

    assert await URLCollector._try_apply_initial_collection_config(collector) is False
    assert collector.common_detail_xpath is None


@pytest.mark.asyncio
async def test_url_collector_tries_multiple_initial_profile_candidates() -> None:
    collector = URLCollector.__new__(URLCollector)
    first = CollectionConfig(common_detail_xpath="//bad")
    second = CollectionConfig(common_detail_xpath="//good", profile_key="candidate-2")
    collector.initial_collection_config = first
    collector.initial_collection_config_candidates = [first, second]
    collector.common_detail_xpath = None
    collector.nav_steps = []
    collector.profile_validation_status = "miss"
    collector.profile_reject_reason = ""
    collector.pagination_handler = None
    collector.navigation_handler = SimpleNamespace()

    async def preview_urls() -> list[str]:
        if collector.common_detail_xpath == "//good":
            return ["https://example.com/detail/1"]
        return []

    collector._preview_urls_with_xpath = preview_urls
    collector._apply_initial_pagination_config = lambda candidate: None
    collector._mark_profile_rejected = URLCollector._mark_profile_rejected.__get__(collector, URLCollector)

    assert await URLCollector._try_apply_initial_collection_config(collector) is True
    assert collector.initial_collection_config is second
    assert collector.common_detail_xpath == "//good"


@pytest.mark.asyncio
async def test_url_collector_restores_nav_steps_after_failed_candidate_preview() -> None:
    collector = URLCollector.__new__(URLCollector)
    first = CollectionConfig(
        common_detail_xpath="//bad",
        nav_steps=[{"action": "click", "target_text": "tab-a"}],
    )
    second = CollectionConfig(
        common_detail_xpath="//good",
        nav_steps=[{"action": "click", "target_text": "tab-b"}],
        profile_key="candidate-2",
    )
    replayed_steps: list[list[dict[str, str]]] = []

    async def replay_nav_steps(nav_steps: list[dict[str, str]]):
        replayed_steps.append([dict(step) for step in nav_steps])
        return True

    async def preview_urls() -> list[str]:
        if collector.common_detail_xpath == "//good" and collector.nav_steps == second.nav_steps:
            return ["https://example.com/detail/1"]
        return []

    collector.initial_collection_config = first
    collector.initial_collection_config_candidates = [first, second]
    collector.common_detail_xpath = "//existing"
    collector.nav_steps = [{"action": "click", "target_text": "existing"}]
    collector.profile_validation_status = "miss"
    collector.profile_reject_reason = ""
    collector.pagination_handler = None
    collector.navigation_handler = SimpleNamespace(replay_nav_steps=replay_nav_steps)
    collector._preview_urls_with_xpath = preview_urls
    collector._apply_initial_pagination_config = lambda candidate: None
    collector._mark_profile_rejected = URLCollector._mark_profile_rejected.__get__(collector, URLCollector)

    assert await URLCollector._try_apply_initial_collection_config(collector) is True
    assert collector.initial_collection_config is second
    assert collector.nav_steps == second.nav_steps
    assert replayed_steps == [first.nav_steps, second.nav_steps]
