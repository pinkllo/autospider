from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from autospider.contexts.planning.application.dto import (
    CreatePlanInput,
    TaskClarifiedEventDTO,
    TaskPlanDTO,
)
from autospider.contexts.planning.application.use_cases.create_plan import CreatePlan
from autospider.contexts.planning.domain.model import ExecutionBrief, SubTask
from autospider.contexts.planning.domain.ports import PlanRepository
from autospider.platform.shared_kernel.result import ResultEnvelope


class PlanRepositoryFactory(Protocol):
    def __call__(self, *, site_url: str, user_request: str, output_dir: str) -> PlanRepository: ...


@dataclass(frozen=True, slots=True)
class TaskClarifiedHandler:
    repository_factory: PlanRepositoryFactory

    def handle(self, payload: TaskClarifiedEventDTO) -> ResultEnvelope[TaskPlanDTO]:
        task = dict(payload.task)
        repository = self.repository_factory(
            site_url=str(task.get("list_url") or ""),
            user_request=str(task.get("task_description") or ""),
            output_dir=payload.output_dir,
        )
        create_plan = CreatePlan(repository)
        command = CreatePlanInput(
            original_request=str(task.get("task_description") or ""),
            site_url=str(task.get("list_url") or ""),
            subtasks=[_build_seed_subtask(task)],
        )
        return create_plan.run(command)


def _build_seed_subtask(task: dict[str, object]) -> SubTask:
    description = str(task.get("task_description") or "").strip()
    return SubTask(
        id=uuid4().hex,
        name=_subtask_name(task, description),
        list_url=str(task.get("list_url") or ""),
        task_description=description,
        fields=list(task.get("fields") or []),
        max_pages=_optional_int(task.get("max_pages")),
        target_url_count=_optional_int(task.get("target_url_count")),
        per_subtask_target_count=_optional_int(task.get("per_group_target_count")),
        execution_brief=ExecutionBrief(objective=description),
    )


def _subtask_name(task: dict[str, object], description: str) -> str:
    intent = str(task.get("intent") or "").strip()
    if intent:
        return intent
    return description[:48] or "seed_subtask"


def _optional_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    return int(value)
