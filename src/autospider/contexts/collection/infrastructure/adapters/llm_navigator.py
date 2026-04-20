"""Collection adapter for LLM-driven navigation decisions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from autospider.platform.observability.logger import get_logger
from autospider.platform.shared_kernel.utils.paths import get_prompt_path
from autospider.contexts.collection.infrastructure.adapters._llm_decision import (
    CollectorDecisionMixin,
)
from autospider.contexts.collection.infrastructure.adapters._llm_pagination import (
    CollectorPaginationMixin,
)

if TYPE_CHECKING:
    from autospider.legacy.common.llm import LLMDecider
    from playwright.async_api import Page

logger = get_logger(__name__)


class LLMDecisionMaker(CollectorDecisionMixin, CollectorPaginationMixin):
    """LLM 决策制定器，负责调用 LLM 进行决策。"""

    prompt_template_path = get_prompt_path("url_collector.yaml")

    def __init__(
        self,
        page: "Page",
        decider: "LLMDecider",
        task_description: str,
        collected_urls: list[str],
        visited_detail_urls: set[str],
        list_url: str,
        selected_skills_context: str = "",
        selected_skills: list[dict] | None = None,
        execution_brief: dict | None = None,
        decision_context: dict | None = None,
    ):
        self.page = page
        self.decider = decider
        self.task_description = task_description
        self.collected_urls = collected_urls
        self.visited_detail_urls = visited_detail_urls
        self.list_url = list_url
        self.selected_skills_context = str(selected_skills_context or "")
        self.selected_skills = list(selected_skills or [])
        self.execution_brief = dict(execution_brief or {})
        self.decision_context = dict(decision_context or {})
