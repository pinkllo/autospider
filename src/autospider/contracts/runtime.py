"""Runtime contracts for execution, dispatch, and aggregation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .execution import ExecutionRequest, PipelineMode, ResumeMode


class SubtaskOutcomeType(str, Enum):
    SYSTEM_FAILURE = "system_failure"
    BUSINESS_FAILURE = "business_failure"
    NO_DATA = "no_data"
    EXPANDED = "expanded"
    SUCCESS = "success"


@dataclass(frozen=True, slots=True)
class TaskIdentity:
    list_url: str
    anchor_url: str = ""
    page_state_signature: str = ""
    variant_label: str = ""
    task_description: str = ""
    field_names: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class InfraConfig:
    browser_headless_default: bool
    browser_timeout_ms: int
    pipeline_mode_default: PipelineMode
    pipeline_consumer_concurrency: int
    planner_max_concurrent_subtasks: int
    redis_enabled: bool
    checkpoint_enabled: bool


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    request: ExecutionRequest
    identity: TaskIdentity
    fields: tuple[Any, ...]
    pipeline_mode: PipelineMode
    consumer_concurrency: int
    max_concurrent: int
    global_browser_budget: int
    resume_mode: ResumeMode
    execution_id: str
    selected_skills: tuple[dict[str, str], ...] = ()
    plan_knowledge: str = ""
    task_plan_snapshot: dict[str, Any] = field(default_factory=dict)
    plan_journal: tuple[dict[str, Any], ...] = ()
    initial_nav_steps: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class PipelineOutcome:
    summary: dict[str, Any]
    collection_config: dict[str, Any]
    extraction_config: dict[str, Any]
    validation_failures: tuple[dict[str, Any], ...]
    extraction_evidence: tuple[dict[str, Any], ...]
    committed_records: tuple[dict[str, Any], ...]
    items_file: str = ""
    summary_file: str = ""


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
