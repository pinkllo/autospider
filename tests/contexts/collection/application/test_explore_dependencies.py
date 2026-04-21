from __future__ import annotations

from pathlib import Path

import pytest

from autospider.contexts.collection.application.use_cases.collect_urls import URLCollector
from autospider.contexts.collection.application.use_cases.explore_dependencies import (
    CollectionExploreDependencies,
    build_collection_explore_dependencies,
)
from autospider.contexts.collection.infrastructure.crawler.explore.config_generator import (
    ConfigGenerator,
)


class _FakeSkillRepository:
    pass


class _FakeSkillRuntime:
    def __init__(self, repository: object | None = None) -> None:
        self.repository = repository

    async def get_or_select(self, **_kwargs) -> list[object]:
        return []

    def format_selected_skills_context(self, _bodies: object) -> str:
        return ""

    def load_selected_bodies(self, _selected: list[object]) -> list[str]:
        return []


class _FakeDecider:
    def __init__(self) -> None:
        self.llm = object()
        self.task_plan = None

    async def decide(self, *_args, **_kwargs) -> None:
        return None


class _FakeXPathExtractor:
    def extract_common_xpath(self, _detail_visits: list[object]) -> str | None:
        return "//a"


class _FakeConfigPersistence:
    def __init__(self, config_dir: str | Path = "output") -> None:
        self.config_dir = Path(config_dir)
        self.saved: list[object] = []

    def save(self, config: object) -> None:
        self.saved.append(config)

    def load(self) -> None:
        return None

    def exists(self) -> bool:
        return False


class _FakeScriptGenerator:
    def __init__(
        self,
        output_dir: str = "output",
        config_persistence: _FakeConfigPersistence | None = None,
    ) -> None:
        self.output_dir = output_dir
        self.config_persistence = config_persistence

    async def generate_scrapy_playwright_script(
        self,
        list_url: str,
        task_description: str,
        detail_visits: list[dict[str, object]],
        nav_steps: list[dict[str, object]],
        collected_urls: list[str],
        common_detail_xpath: str | None = None,
    ) -> str:
        return ""


def _workspace_tmp(name: str) -> Path:
    path = Path(".tmp") / "collection_application_tests" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def _build_fake_dependencies(
    *,
    include_script_generator: bool = True,
) -> CollectionExploreDependencies:
    persistence = _FakeConfigPersistence()
    script_generator = _FakeScriptGenerator(config_persistence=persistence)
    return CollectionExploreDependencies(
        skill_runtime=_FakeSkillRuntime(),
        decider=_FakeDecider(),
        xpath_extractor=_FakeXPathExtractor(),
        config_persistence=persistence,
        script_generator=script_generator if include_script_generator else None,
    )


def test_build_collection_explore_dependencies_shares_config_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _FakeSkillRuntime()
    output_dir = _workspace_tmp("deps_builder")
    monkeypatch.setattr("autospider.platform.llm.decider.LLMDecider", _FakeDecider)
    monkeypatch.setattr(
        "autospider.contexts.collection.infrastructure.adapters.scrapy_generator.ScriptGenerator",
        _FakeScriptGenerator,
    )
    monkeypatch.setattr(
        "autospider.contexts.collection.infrastructure.crawler.collector.xpath_extractor.XPathExtractor",
        _FakeXPathExtractor,
    )
    monkeypatch.setattr(
        "autospider.contexts.collection.infrastructure.repositories.config_repository.ConfigPersistence",
        _FakeConfigPersistence,
    )
    monkeypatch.setattr(
        "autospider.contexts.experience.application.use_cases.skill_runtime.SkillRuntime",
        _FakeSkillRuntime,
    )
    monkeypatch.setattr(
        "autospider.contexts.experience.infrastructure.repositories.skill_repository.SkillRepository",
        _FakeSkillRepository,
    )

    deps = build_collection_explore_dependencies(
        output_dir=str(output_dir),
        skill_runtime=runtime,
    )

    assert deps.skill_runtime is runtime
    assert isinstance(deps.decider, _FakeDecider)
    assert isinstance(deps.xpath_extractor, _FakeXPathExtractor)
    assert isinstance(deps.config_persistence, _FakeConfigPersistence)
    assert isinstance(deps.script_generator, _FakeScriptGenerator)
    assert deps.script_generator.config_persistence is deps.config_persistence


def test_url_collector_uses_injected_explore_dependencies() -> None:
    deps = _build_fake_dependencies()
    output_dir = _workspace_tmp("collector_injected")

    collector = URLCollector(
        page=object(),
        list_url="https://example.com/list",
        task_description="collect items",
        output_dir=str(output_dir),
        explore_dependencies=deps,
    )

    assert collector.skill_runtime is deps.skill_runtime
    assert collector.decider is deps.decider
    assert collector.xpath_extractor is deps.xpath_extractor
    assert collector.config_persistence is deps.config_persistence
    assert collector.script_generator is deps.script_generator


def test_url_collector_requires_script_generator_in_explore_dependencies(
) -> None:
    deps = _build_fake_dependencies(include_script_generator=False)
    output_dir = _workspace_tmp("collector_missing_script_generator")

    with pytest.raises(ValueError, match="collection_explore_dependencies_missing_script_generator"):
        URLCollector(
            page=object(),
            list_url="https://example.com/list",
            task_description="collect items",
            output_dir=str(output_dir),
            explore_dependencies=deps,
        )


def test_config_generator_uses_injected_explore_dependencies() -> None:
    deps = _build_fake_dependencies()
    output_dir = _workspace_tmp("config_generator_injected")

    generator = ConfigGenerator(
        page=object(),
        list_url="https://example.com/list",
        task_description="collect items",
        output_dir=str(output_dir),
        explore_dependencies=deps,
    )

    assert generator.skill_runtime is deps.skill_runtime
    assert generator.decider is deps.decider
    assert generator.xpath_extractor is deps.xpath_extractor
    assert generator.config_persistence is deps.config_persistence
