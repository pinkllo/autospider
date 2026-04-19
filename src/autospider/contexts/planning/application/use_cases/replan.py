from __future__ import annotations

from autospider.contexts.planning.application.dto import ReplanInput, TaskPlanDTO, to_task_plan_dto
from autospider.contexts.planning.domain.policies import ReplanStrategy
from autospider.contexts.planning.domain.ports import PlanRepository
from autospider.platform.shared_kernel.result import ResultEnvelope
from autospider.platform.shared_kernel.trace import get_trace_id


class Replan:
    def __init__(self, repository: PlanRepository, strategy: ReplanStrategy | None = None) -> None:
        self._repository = repository
        self._strategy = strategy or ReplanStrategy()

    def run(self, command: ReplanInput) -> ResultEnvelope[TaskPlanDTO]:
        trace_id = _require_trace_id()
        updated = self._strategy.apply(
            plan=command.plan,
            reason=command.reason,
            failed_subtask_id=command.failed_subtask_id,
        )
        saved = self._repository.save_plan(updated)
        return ResultEnvelope.success(data=to_task_plan_dto(saved), trace_id=trace_id)


def _require_trace_id() -> str:
    trace_id = get_trace_id()
    if not trace_id:
        raise RuntimeError("trace_id is not set")
    return trace_id
