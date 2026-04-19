from __future__ import annotations

from autospider.contexts.planning.application.dto import CreatePlanInput, TaskPlanDTO, to_task_plan_dto
from autospider.contexts.planning.domain.ports import PlanRepository
from autospider.platform.shared_kernel.errors import DomainError
from autospider.platform.shared_kernel.result import ErrorInfo, ResultEnvelope
from autospider.platform.shared_kernel.trace import get_trace_id


class CreatePlan:
    def __init__(self, repository: PlanRepository) -> None:
        self._repository = repository

    def run(self, command: CreatePlanInput) -> ResultEnvelope[TaskPlanDTO]:
        trace_id = _require_trace_id()
        if not command.original_request.strip():
            return _failed(trace_id, "planning.empty_request", "planning request is empty")
        if not command.site_url.strip():
            return _failed(trace_id, "planning.empty_site_url", "planning site_url is empty")
        try:
            plan = self._repository.build_plan(
                list(command.subtasks),
                nodes=list(command.nodes),
                journal=list(command.journal),
            )
            saved = self._repository.save_plan(plan)
        except DomainError as exc:
            return _failed(trace_id, exc.code, str(exc))
        return ResultEnvelope.success(data=to_task_plan_dto(saved), trace_id=trace_id)


def _require_trace_id() -> str:
    trace_id = get_trace_id()
    if not trace_id:
        raise RuntimeError("trace_id is not set")
    return trace_id


def _failed(trace_id: str, code: str, message: str) -> ResultEnvelope[TaskPlanDTO]:
    return ResultEnvelope.failed(
        trace_id=trace_id,
        errors=[ErrorInfo(kind="domain", code=code, message=message)],
    )
