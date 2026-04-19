from __future__ import annotations

from typing import Protocol

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
