from __future__ import annotations

from autospider.contexts.planning.application.dto import (
    ClassifyProtocolViolationInput,
    ClassifyRuntimeExceptionInput,
    CreatePlanInput,
    DecomposePlanInput,
    ReplanInput,
)
from autospider.contexts.planning.application.handlers import SubTaskFailedHandler
from autospider.contexts.planning.application.use_cases import (
    ClassifyRuntimeException,
    CreatePlan,
    DecomposePlan,
    Replan,
)
from autospider.contexts.planning.domain.model import SubTask, TaskPlan
from autospider.platform.shared_kernel.trace import clear_run_context, set_run_context


class InMemoryPlanRepository:
    def __init__(self) -> None:
        self.saved_plan: TaskPlan | None = None

    def build_plan(self, subtasks, *, nodes=None, journal=None) -> TaskPlan:
        return TaskPlan(
            plan_id="plan-1",
            original_request="抓取公告",
            site_url="https://example.com/notices",
            subtasks=list(subtasks),
            nodes=list(nodes or []),
            journal=list(journal or []),
            total_subtasks=len(subtasks),
            created_at="created-at",
            updated_at="updated-at",
        )

    def create_empty_plan(self) -> TaskPlan:
        return self.build_plan([])

    def save_plan(self, plan: TaskPlan) -> TaskPlan:
        self.saved_plan = plan
        return plan


def _set_trace(trace_id: str) -> None:
    set_run_context(run_id=None, trace_id=trace_id)


def test_create_plan_returns_success() -> None:
    _set_trace("trace-planning-create")
    repository = InMemoryPlanRepository()
    result = CreatePlan(repository).run(
        CreatePlanInput(original_request="抓取公告", site_url="https://example.com/notices")
    )

    assert result.status == "success"
    assert result.data is not None
    assert result.data.plan_id == "plan-1"
    clear_run_context()


def test_decompose_plan_appends_subtasks() -> None:
    _set_trace("trace-planning-decompose")
    repository = InMemoryPlanRepository()
    plan = repository.create_empty_plan()
    result = DecomposePlan(repository).run(
        DecomposePlanInput(
            plan=plan,
            subtasks=[
                SubTask(
                    id="s1",
                    name="公告",
                    list_url="https://example.com/notices",
                    task_description="抓取",
                )
            ],
        )
    )

    assert result.status == "success"
    assert result.data is not None
    assert result.data.total_subtasks == 1
    clear_run_context()


def test_replan_appends_journal_entry() -> None:
    _set_trace("trace-planning-replan")
    repository = InMemoryPlanRepository()
    plan = repository.create_empty_plan()
    result = Replan(repository).run(
        ReplanInput(plan=plan, reason="需要避开超时页面", failed_subtask_id="subtask-1")
    )

    assert result.status == "success"
    assert result.data is not None
    assert result.data.journal[-1]["action"] == "replan"
    clear_run_context()


def test_subtask_failed_handler_delegates_to_replan() -> None:
    _set_trace("trace-planning-handler")
    repository = InMemoryPlanRepository()
    plan = repository.create_empty_plan()
    result = SubTaskFailedHandler(Replan(repository)).handle(
        plan=plan,
        reason="state mismatch",
        failed_subtask_id="subtask-2",
    )

    assert result.status == "success"
    assert result.data is not None
    assert result.data.journal[-1]["node_id"] == "subtask-2"
    clear_run_context()


def test_classify_runtime_exception_and_protocol_violation() -> None:
    _set_trace("trace-planning-classify")
    use_case = ClassifyRuntimeException()

    runtime_result = use_case.run(
        ClassifyRuntimeExceptionInput(
            component="planner",
            error=TimeoutError("planner timed out"),
        )
    )
    protocol_result = use_case.classify_protocol_violation(
        ClassifyProtocolViolationInput(
            component="planner",
            diagnostics={"action": "parse", "response_text": "bad payload"},
        )
    )

    assert runtime_result.data is not None
    assert runtime_result.data.category == "transient"
    assert protocol_result.data is not None
    assert protocol_result.data.detail == "invalid_protocol_message"
    clear_run_context()
