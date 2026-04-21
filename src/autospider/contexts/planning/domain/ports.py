from __future__ import annotations

from typing import Any, Protocol

from autospider.contexts.planning.domain.model import PlanJournalEntry, PlanNode, SubTask, TaskPlan


class PlanRepository(Protocol):
    def build_plan(
        self,
        subtasks: list[SubTask],
        *,
        nodes: list[PlanNode] | None = None,
        journal: list[PlanJournalEntry] | None = None,
    ) -> TaskPlan: ...

    def create_empty_plan(self) -> TaskPlan: ...

    def save_plan(self, plan: TaskPlan) -> TaskPlan: ...


class NavigationStepReplayer(Protocol):
    async def replay_nav_steps(self, nav_steps: list[dict[str, object]]) -> object: ...


class NavigationStepReplayerFactory(Protocol):
    def __call__(
        self,
        *,
        page: Any,
        target_url: str,
        max_nav_steps: int,
    ) -> NavigationStepReplayer: ...
