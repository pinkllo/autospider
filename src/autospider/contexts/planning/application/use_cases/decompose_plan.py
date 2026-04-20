from __future__ import annotations

from autospider.contexts.planning.application.dto import (
    DecomposePlanInput,
    TaskPlanDTO,
    to_task_plan_dto,
)
from autospider.contexts.planning.domain.ports import PlanRepository
from autospider.platform.shared_kernel.result import ResultEnvelope
from autospider.platform.shared_kernel.trace import get_trace_id


class DecomposePlan:
    def __init__(self, repository: PlanRepository) -> None:
        self._repository = repository

    def run(self, command: DecomposePlanInput) -> ResultEnvelope[TaskPlanDTO]:
        trace_id = _require_trace_id()
        subtasks = [*command.plan.subtasks, *command.subtasks]
        updated = command.plan.model_copy(
            update={
                "subtasks": subtasks,
                "total_subtasks": len(subtasks),
            }
        )
        saved = self._repository.save_plan(updated)
        return ResultEnvelope.success(data=to_task_plan_dto(saved), trace_id=trace_id)


def _require_trace_id() -> str:
    trace_id = get_trace_id()
    if not trace_id:
        raise RuntimeError("trace_id is not set")
    return trace_id
