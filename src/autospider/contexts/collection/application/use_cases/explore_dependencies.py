"""Shared dependency container for collection exploration flows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from autospider.contexts.collection.infrastructure.repositories.config_repository import (
    CollectionConfig,
)


class SkillRuntimeLike(Protocol):
    async def get_or_select(self, **kwargs: Any) -> list[Any]: ...

    def format_selected_skills_context(self, bodies: Any) -> str: ...

    def load_selected_bodies(self, selected: list[Any]) -> Any: ...


class CollectionDeciderLike(Protocol):
    llm: Any
    task_plan: str | None

    async def decide(self, *args: Any, **kwargs: Any) -> Any: ...


class XPathExtractorLike(Protocol):
    def extract_common_xpath(self, detail_visits: list[Any]) -> str | None: ...


class ConfigPersistenceLike(Protocol):
    def save(self, config: CollectionConfig) -> None: ...

    def load(self) -> CollectionConfig | None: ...

    def exists(self) -> bool: ...


class ScriptGeneratorLike(Protocol):
    async def generate_scrapy_playwright_script(
        self,
        list_url: str,
        task_description: str,
        detail_visits: list[dict[str, Any]],
        nav_steps: list[dict[str, Any]],
        collected_urls: list[str],
        common_detail_xpath: str | None = None,
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class CollectionExploreDependencies:
    skill_runtime: SkillRuntimeLike
    decider: CollectionDeciderLike
    xpath_extractor: XPathExtractorLike
    config_persistence: ConfigPersistenceLike
    script_generator: ScriptGeneratorLike | None = None


def build_collection_explore_dependencies(
    *,
    output_dir: str = "output",
    skill_runtime: SkillRuntimeLike | None = None,
) -> CollectionExploreDependencies:
    from autospider.platform.llm.decider import LLMDecider
    from autospider.contexts.collection.infrastructure.adapters.scrapy_generator import (
        ScriptGenerator,
    )
    from autospider.contexts.collection.infrastructure.crawler.collector.xpath_extractor import (
        XPathExtractor,
    )
    from autospider.contexts.collection.infrastructure.repositories.config_repository import (
        ConfigPersistence,
    )
    from autospider.contexts.experience.application.use_cases.skill_runtime import SkillRuntime
    from autospider.contexts.experience.infrastructure.repositories.skill_repository import (
        SkillRepository,
    )

    resolved_skill_runtime = skill_runtime or SkillRuntime(SkillRepository())
    config_persistence = ConfigPersistence(output_dir)
    return CollectionExploreDependencies(
        skill_runtime=resolved_skill_runtime,
        decider=LLMDecider(),
        xpath_extractor=XPathExtractor(),
        config_persistence=config_persistence,
        script_generator=ScriptGenerator(
            output_dir=output_dir,
            config_persistence=config_persistence,
        ),
    )
