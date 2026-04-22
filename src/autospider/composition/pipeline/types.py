"""Compatibility facade for pipeline DTOs."""

from .request_types import ExecutionContext, ExecutionRequest, InfraConfig, PipelineMode, ResumeMode, TaskIdentity
from .result_types import DurabilityState, PipelineOutcome, PipelineRunResult, PipelineRunSummary, PromotionState
from .subtask_types import (
    AggregationEligibility,
    AggregationFailure,
    AggregationOutcome,
    AggregationReport,
    AggregationSubtaskDetail,
    ExpandRequest,
    SubtaskOutcome,
    SubtaskOutcomeType,
    SubtaskRunSummary,
)

__all__ = [
    "AggregationEligibility",
    "AggregationFailure",
    "AggregationOutcome",
    "AggregationReport",
    "AggregationSubtaskDetail",
    "DurabilityState",
    "ExecutionContext",
    "ExecutionRequest",
    "ExpandRequest",
    "InfraConfig",
    "PipelineMode",
    "PipelineOutcome",
    "PipelineRunResult",
    "PipelineRunSummary",
    "PromotionState",
    "ResumeMode",
    "SubtaskOutcome",
    "SubtaskOutcomeType",
    "SubtaskRunSummary",
    "TaskIdentity",
]
