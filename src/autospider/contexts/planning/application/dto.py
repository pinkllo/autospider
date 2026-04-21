from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from autospider.contexts.planning.domain.model import (
    PlanJournalEntry,
    PlanNode,
    SubTask,
    TaskPlan,
)


class CreatePlanInput(BaseModel):
    original_request: str
    site_url: str
    subtasks: list[SubTask] = Field(default_factory=list)
    nodes: list[PlanNode] = Field(default_factory=list)
    journal: list[PlanJournalEntry] = Field(default_factory=list)


class DecomposePlanInput(BaseModel):
    plan: TaskPlan
    subtasks: list[SubTask] = Field(default_factory=list)


class ReplanInput(BaseModel):
    plan: TaskPlan
    reason: str
    failed_subtask_id: str | None = None


class ClassifyRuntimeExceptionInput(BaseModel):
    component: str
    error: BaseException

    model_config = {"arbitrary_types_allowed": True}


class ClassifyProtocolViolationInput(BaseModel):
    component: str
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class TaskPlanDTO(BaseModel):
    plan_id: str
    original_request: str
    site_url: str
    subtasks: list[dict[str, Any]] = Field(default_factory=list)
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    journal: list[dict[str, Any]] = Field(default_factory=list)
    total_subtasks: int
    created_at: str
    updated_at: str


class FailureSignalDTO(BaseModel):
    category: str
    detail: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskClarifiedEventDTO(BaseModel):
    session_id: str
    output_dir: str = "output"
    task: dict[str, Any] = Field(default_factory=dict)


def to_task_plan_dto(plan: TaskPlan) -> TaskPlanDTO:
    return TaskPlanDTO(
        plan_id=plan.plan_id,
        original_request=plan.original_request,
        site_url=plan.site_url,
        subtasks=[item.model_dump(mode="python") for item in plan.subtasks],
        nodes=[item.model_dump(mode="python") for item in plan.nodes],
        journal=[item.model_dump(mode="python") for item in plan.journal],
        total_subtasks=plan.total_subtasks,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )
