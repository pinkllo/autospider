from __future__ import annotations

from autospider.contexts.planning.application.dto import ReplanInput, TaskPlanDTO
from autospider.contexts.planning.application.use_cases.replan import Replan
from autospider.contexts.planning.domain.model import TaskPlan
from autospider.platform.shared_kernel.result import ResultEnvelope


class SubTaskFailedHandler:
    def __init__(self, replan_use_case: Replan) -> None:
        self._replan_use_case = replan_use_case

    def handle(
        self,
        *,
        plan: TaskPlan,
        reason: str,
        failed_subtask_id: str | None = None,
    ) -> ResultEnvelope[TaskPlanDTO]:
        return self._replan_use_case.run(
            ReplanInput(
                plan=plan,
                reason=reason,
                failed_subtask_id=failed_subtask_id,
            )
        )
