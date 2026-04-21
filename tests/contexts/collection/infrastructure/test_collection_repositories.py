from __future__ import annotations

from pathlib import Path

from autospider.contexts.collection.infrastructure.repositories.config_repository import (
    CollectionConfig,
    ConfigPersistence,
    coerce_collection_config,
)
from autospider.contexts.collection.infrastructure.repositories.field_xpath_repository import (
    normalize_xpath_domain,
)
from autospider.contexts.collection.infrastructure.repositories.progress_repository import (
    CollectionProgress,
    ProgressPersistence,
    coerce_collection_progress,
)
from autospider.contexts.collection.infrastructure.adapters.scrapy_generator import (
    ScriptGenerator,
)


def _workspace_tmp(name: str) -> Path:
    path = Path(".tmp") / "collection_repo_tests" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_config_persistence_round_trip() -> None:
    persistence = ConfigPersistence(config_dir=_workspace_tmp("config"))
    config = CollectionConfig(
        list_url="https://example.com/list",
        anchor_url="https://example.com",
        page_state_signature="state-1",
        task_description="collect items",
        nav_steps=[{"action": "click", "target_text": "News"}],
    )

    persistence.save(config)
    loaded = persistence.load()

    assert loaded is not None
    assert loaded.list_url == config.list_url
    assert loaded.anchor_url == config.anchor_url
    assert loaded.nav_steps == config.nav_steps
    assert loaded.created_at
    assert loaded.updated_at
    assert coerce_collection_config(loaded).to_payload()["list_url"] == config.list_url


def test_progress_persistence_round_trip() -> None:
    persistence = ProgressPersistence(output_dir=_workspace_tmp("progress"))
    progress = CollectionProgress(
        status="RUNNING",
        list_url="https://example.com/list",
        task_description="collect items",
        current_page_num=3,
        collected_count=12,
        consecutive_success_pages=2,
    )

    persistence.save_progress(progress)
    loaded = persistence.load_progress()

    assert loaded is not None
    assert loaded.current_page_num == 3
    assert loaded.collected_count == 12
    assert loaded.last_updated
    assert persistence.has_checkpoint() is True
    assert coerce_collection_progress(loaded).to_payload()["status"] == "RUNNING"


def test_normalize_xpath_domain_removes_www_prefix() -> None:
    assert normalize_xpath_domain("https://www.example.com/path?q=1") == "example.com"


def test_script_generator_extracts_common_detail_xpath() -> None:
    generator = ScriptGenerator()
    visits = [
        {"clicked_element_xpath_candidates": [{"xpath": "/html/body/div[1]/a[1]", "priority": 1}]},
        {"clicked_element_xpath_candidates": [{"xpath": "/html/body/div[2]/a[1]", "priority": 1}]},
    ]

    assert generator._extract_detail_xpath(visits) == "/html/body/div/a"


def test_script_generator_hydrates_missing_config() -> None:
    output_dir = _workspace_tmp("script_generator")
    persistence = ConfigPersistence(config_dir=output_dir)
    persistence.save(
        CollectionConfig(
            nav_steps=[{"action": "click", "target_text": "News"}],
            common_detail_xpath="//a[@class='detail']",
            list_url="https://example.com/list",
            task_description="collect items",
        )
    )
    generator = ScriptGenerator(config_persistence=persistence)

    nav_steps, detail_xpath = generator._hydrate_missing_config([], None)

    assert nav_steps == [{"action": "click", "target_text": "News"}]
    assert detail_xpath == "//a[@class='detail']"
