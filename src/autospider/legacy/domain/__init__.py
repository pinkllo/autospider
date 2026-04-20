"""Compat shim: re-exports of legacy domain models now relocated under contexts.*."""

from autospider.contexts.collection.domain.fields import FieldDefinition
from autospider.contexts.planning.domain import SubTask, SubTaskStatus, TaskPlan
from autospider.contexts.planning.domain.runtime import SubTaskRuntimeState, SubTaskRuntimeSummary

__all__ = [
    "FieldDefinition",
    "SubTask",
    "SubTaskRuntimeState",
    "SubTaskRuntimeSummary",
    "SubTaskStatus",
    "TaskPlan",
]