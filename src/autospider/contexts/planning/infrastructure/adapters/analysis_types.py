from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from autospider.contexts.planning.domain import ExecutionBrief, SubTask

if TYPE_CHECKING:
    from playwright.async_api import Page

    from autospider.contexts.planning.domain import PlannerIntent


@dataclass
class ResolvedPlannerVariant:
    resolved_url: str
    anchor_url: str
    nav_steps: list[dict] = field(default_factory=list)
    page_state_signature: str = ""
    variant_label: str = ""
    context: dict[str, str] = field(default_factory=dict)
    same_page_variant: bool = False


@dataclass
class RuntimeSubtaskPlanResult:
    page_type: str
    analysis: dict[str, Any]
    children: list[SubTask] = field(default_factory=list)
    collect_task_description: str = ""
    collect_execution_brief: ExecutionBrief = field(default_factory=ExecutionBrief)


class PlannerAnalysisRuntime(Protocol):
    page: Page
    llm: Any
    site_url: str
    user_request: str
    planner_intent: PlannerIntent
    selected_skills_context: str
    selected_skills: list[dict]
    prior_failures: list[dict[str, Any]]
    decision_context: dict[str, Any]
    world_snapshot: dict[str, Any]

    def _format_context_path(self, context: dict[str, str] | None) -> str: ...

    def _format_recent_actions(self, nav_steps: list[dict] | None) -> str: ...

    def _build_planner_candidates(self, snapshot: object, max_candidates: int = 30) -> str: ...

    def _post_process_analysis(
        self,
        result: dict,
        snapshot: object,
        *,
        node_context: dict[str, str] | None = None,
    ) -> dict: ...
