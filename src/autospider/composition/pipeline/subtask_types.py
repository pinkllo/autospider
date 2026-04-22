"""Subtask and aggregation DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from .result_types import PipelineRunSummary


class AggregationEligibility(str, Enum):
    INCLUDED = "included"
    EXCLUDED = "excluded"
    FAILED = "failed"


class SubtaskOutcomeType(str, Enum):
    SYSTEM_FAILURE = "system_failure"
    BUSINESS_FAILURE = "business_failure"
    NO_DATA = "no_data"
    EXPANDED = "expanded"
    SUCCESS = "success"


class SubtaskRunSummary(BaseModel):
    id: str
    name: str
    task_description: str = ""
    status: str = ""
    error: str = ""
    result_file: str = ""
    collected_count: int = 0
    summary: PipelineRunSummary = Field(default_factory=PipelineRunSummary)


class AggregationSubtaskDetail(BaseModel):
    id: str
    name: str
    status: str
    eligibility: AggregationEligibility
    reason: str = ""
    excluded_reason: str = ""
    items: int = 0
    result_file: str = ""
    conflict_count: int = 0


class AggregationReport(BaseModel):
    merged_items: int = 0
    unique_urls: int = 0
    eligible_subtasks: int = 0
    excluded_subtasks: int = 0
    failed_subtasks: int = 0
    conflict_count: int = 0
    failure_reasons: list[str] = Field(default_factory=list)
    subtask_details: list[AggregationSubtaskDetail] = Field(default_factory=list)
    merged_file: str = ""
    summary_file: str = ""


class AggregationFailure(RuntimeError):
    """Raised when aggregation cannot produce a trustworthy merged result."""

    def __init__(self, report: AggregationReport):
        self.report = report
        reasons = ", ".join(report.failure_reasons) or "aggregation_failed"
        super().__init__(reasons)


@dataclass(frozen=True, slots=True)
class ExpandRequest:
    parent_subtask_id: str
    spawned_subtasks: tuple[dict[str, Any], ...]
    journal_entries: tuple[dict[str, Any], ...]
    reason: str = ""


@dataclass(frozen=True, slots=True)
class SubtaskOutcome:
    subtask_id: str
    status: str
    outcome_type: SubtaskOutcomeType
    error: str = ""
    result_file: str = ""
    collected_count: int = 0
    summary: dict[str, Any] = field(default_factory=dict)
    expand_request: ExpandRequest | None = None


@dataclass(frozen=True, slots=True)
class AggregationOutcome:
    merged_items: int
    unique_urls: int
    eligible_subtasks: int
    excluded_subtasks: int
    failed_subtasks: int
    conflict_count: int
    merged_file: str
    summary_file: str
    failure_reasons: tuple[str, ...] = ()
