"""Execution DTOs shared by graph and pipeline."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..common.grouping_semantics import normalize_grouping_semantics


def _parse_optional_bool(raw_value: Any) -> bool | None:
    if raw_value is None:
        return None
    if isinstance(raw_value, bool):
        return raw_value
    text = str(raw_value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off", ""}:
        return False
    raise ValueError(f"invalid_optional_bool: {raw_value}")


def _mapping_payload(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _workflow_request_params(world_snapshot: Any) -> dict[str, Any]:
    world = _mapping_payload(world_snapshot)
    request_params = _mapping_payload(world.get("request_params"))
    if request_params:
        return request_params
    world_model = _mapping_payload(world.get("world_model"))
    return _mapping_payload(world_model.get("request_params"))


def _resolve_runtime_decision_context(payload: dict[str, Any], world_snapshot: dict[str, Any]) -> dict[str, Any]:
    workflow_params = _workflow_request_params(world_snapshot)
    workflow_context = _mapping_payload(workflow_params.get("decision_context"))
    if workflow_context:
        return workflow_context
    return _mapping_payload(payload.get("decision_context"))


def _resolve_runtime_failure_records(payload: dict[str, Any], world_snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    workflow_params = _workflow_request_params(world_snapshot)
    workflow_failures = workflow_params.get("failure_records")
    if isinstance(workflow_failures, list):
        return list(workflow_failures)
    snapshot_failures = world_snapshot.get("failure_records")
    if isinstance(snapshot_failures, list):
        return list(snapshot_failures)
    world_model = _mapping_payload(world_snapshot.get("world_model"))
    model_failures = world_model.get("failure_records")
    if isinstance(model_failures, list):
        return list(model_failures)
    legacy_failures = payload.get("failure_records")
    return list(legacy_failures) if isinstance(legacy_failures, list) else []


class PromotionState(str, Enum):
    REUSABLE = "reusable"
    DIAGNOSTIC_ONLY = "diagnostic_only"
    REJECTED = "rejected"


class DurabilityState(str, Enum):
    STAGED = "staged"
    DURABLE = "durable"
    FAILED_COMMIT = "failed_commit"


class PipelineMode(str, Enum):
    MEMORY = "memory"
    FILE = "file"
    REDIS = "redis"


class ResumeMode(str, Enum):
    FRESH = "fresh"
    RESUME = "resume"


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


class ExecutionRequest(BaseModel):
    """Single normalized request contract for graph and pipeline."""

    list_url: str = ""
    site_url: str = ""
    request: str = ""
    task_description: str = ""
    semantic_signature: str = ""
    strategy_payload: dict[str, Any] = Field(default_factory=dict)
    matched_registry_id: str = ""
    fields: list[dict[str, Any]] = Field(default_factory=list)
    group_by: Literal["none", "category"] = "none"
    per_group_target_count: int | None = None
    total_target_count: int | None = None
    category_discovery_mode: Literal["auto", "manual"] = "auto"
    requested_categories: list[str] = Field(default_factory=list)
    category_examples: list[str] = Field(default_factory=list)
    execution_brief: dict[str, Any] = Field(default_factory=dict)
    output_dir: str = "output"
    headless: bool | None = None
    field_explore_count: int | None = None
    field_validate_count: int | None = None
    consumer_concurrency: int | None = None
    max_pages: int | None = None
    target_url_count: int | None = None
    pipeline_mode: PipelineMode | None = None
    guard_intervention_mode: str = "interrupt"
    guard_thread_id: str = ""
    selected_skills: list[dict[str, str]] = Field(default_factory=list)
    plan_knowledge: str = ""
    task_plan_snapshot: dict[str, Any] = Field(default_factory=dict)
    plan_journal: list[dict[str, Any]] = Field(default_factory=list)
    initial_nav_steps: list[dict[str, Any]] = Field(default_factory=list)
    decision_context: dict[str, Any] = Field(default_factory=dict)
    world_snapshot: dict[str, Any] = Field(default_factory=dict)
    failure_records: list[dict[str, Any]] = Field(default_factory=list)
    anchor_url: str | None = None
    page_state_signature: str = ""
    variant_label: str | None = None
    max_turns: int | None = None
    max_concurrent: int | None = None
    runtime_subtask_max_children: int | None = None
    runtime_subtasks_use_main_model: bool | None = None
    serial_mode: bool = False
    execution_id: str = ""
    resume_mode: ResumeMode = ResumeMode.FRESH
    global_browser_budget: int | None = None

    @classmethod
    def from_params(
        cls,
        params: dict[str, Any],
        *,
        thread_id: str = "",
        guard_intervention_mode: str = "interrupt",
    ) -> "ExecutionRequest":
        payload = dict(params or {})
        grouping = normalize_grouping_semantics(payload)
        world_snapshot = _mapping_payload(payload.get("world_snapshot"))
        headless = _parse_optional_bool(payload["headless"]) if "headless" in payload else None
        task_description = str(payload.get("task_description") or "").strip()
        request = str(payload.get("request") or task_description or "").strip()
        site_url = str(payload.get("site_url") or payload.get("list_url") or "").strip()
        return cls(
            list_url=str(payload.get("list_url") or "").strip(),
            site_url=site_url,
            request=request,
            task_description=task_description,
            semantic_signature=str(payload.get("semantic_signature") or "").strip(),
            strategy_payload=dict(payload.get("strategy_payload") or {}),
            matched_registry_id=str(payload.get("matched_registry_id") or "").strip(),
            fields=list(payload.get("fields") or []),
            group_by=grouping["group_by"],
            per_group_target_count=grouping["per_group_target_count"],
            total_target_count=grouping["total_target_count"],
            category_discovery_mode=grouping["category_discovery_mode"],
            requested_categories=grouping["requested_categories"],
            category_examples=grouping["category_examples"],
            execution_brief=dict(payload.get("execution_brief") or {}),
            output_dir=str(payload.get("output_dir") or "output"),
            headless=headless,
            field_explore_count=payload.get("field_explore_count"),
            field_validate_count=payload.get("field_validate_count"),
            consumer_concurrency=payload.get("consumer_concurrency"),
            max_pages=payload.get("max_pages"),
            target_url_count=payload.get("target_url_count"),
            pipeline_mode=(
                PipelineMode(str(payload.get("pipeline_mode") or "").strip().lower())
                if str(payload.get("pipeline_mode") or "").strip()
                else None
            ),
            guard_intervention_mode=guard_intervention_mode,
            guard_thread_id=thread_id,
            selected_skills=list(payload.get("selected_skills") or []),
            plan_knowledge=str(payload.get("plan_knowledge") or ""),
            task_plan_snapshot=dict(payload.get("task_plan_snapshot") or {}),
            plan_journal=list(payload.get("plan_journal") or []),
            initial_nav_steps=list(payload.get("initial_nav_steps") or []),
            decision_context=_resolve_runtime_decision_context(payload, world_snapshot),
            world_snapshot=world_snapshot,
            failure_records=_resolve_runtime_failure_records(payload, world_snapshot),
            anchor_url=payload.get("anchor_url"),
            page_state_signature=str(payload.get("page_state_signature") or ""),
            variant_label=payload.get("variant_label"),
            max_turns=payload.get("max_turns"),
            max_concurrent=payload.get("max_concurrent"),
            runtime_subtask_max_children=payload.get("runtime_subtask_max_children"),
            runtime_subtasks_use_main_model=payload.get("runtime_subtasks_use_main_model"),
            serial_mode=bool(payload.get("serial_mode")),
            execution_id=str(payload.get("execution_id") or "").strip(),
            resume_mode=ResumeMode(str(payload.get("resume_mode") or ResumeMode.FRESH.value).strip().lower()),
            global_browser_budget=payload.get("global_browser_budget"),
        )


class PipelineRunSummary(BaseModel):
    total_urls: int = 0
    success_count: int = 0
    failed_count: int = 0
    success_rate: float = 0.0
    required_field_success_rate: float = 0.0
    validation_failure_count: int = 0
    execution_state: str = ""
    outcome_state: str = ""
    terminal_reason: str = ""
    promotion_state: PromotionState = PromotionState.REJECTED
    items_file: str = ""
    summary_file: str = ""
    execution_id: str = ""
    durability_state: DurabilityState = DurabilityState.STAGED
    durably_persisted: bool = False

    @classmethod
    def from_raw(cls, raw: dict[str, Any], *, summary_file: str = "") -> "PipelineRunSummary":
        promotion = str(raw.get("promotion_state") or PromotionState.REJECTED.value).strip().lower()
        durability = str(
            raw.get("durability_state")
            or (DurabilityState.DURABLE.value if raw.get("durably_persisted") else DurabilityState.STAGED.value)
        ).strip().lower()
        return cls(
            total_urls=int(raw.get("total_urls", 0) or 0),
            success_count=int(raw.get("success_count", 0) or 0),
            failed_count=int(raw.get("failed_count", 0) or 0),
            success_rate=float(raw.get("success_rate", 0.0) or 0.0),
            required_field_success_rate=float(raw.get("required_field_success_rate", 0.0) or 0.0),
            validation_failure_count=int(raw.get("validation_failure_count", 0) or 0),
            execution_state=str(raw.get("execution_state") or ""),
            outcome_state=str(raw.get("outcome_state") or ""),
            terminal_reason=str(raw.get("terminal_reason") or ""),
            promotion_state=PromotionState(promotion),
            items_file=str(raw.get("items_file") or ""),
            summary_file=str(summary_file or raw.get("summary_file") or ""),
            execution_id=str(raw.get("execution_id") or ""),
            durability_state=DurabilityState(durability),
            durably_persisted=durability == DurabilityState.DURABLE.value,
        )


class PipelineRunResult(BaseModel):
    summary: PipelineRunSummary = Field(default_factory=PipelineRunSummary)
    data: dict[str, Any] = Field(default_factory=dict)
    collection_config: dict[str, Any] = Field(default_factory=dict)
    extraction_config: dict[str, Any] = Field(default_factory=dict)
    validation_failures: list[dict[str, Any]] = Field(default_factory=list)
    extraction_evidence: list[dict[str, Any]] = Field(default_factory=list)
    committed_records: list[dict[str, Any]] = Field(default_factory=list)
    error: str = ""

    @classmethod
    def from_raw(cls, raw: dict[str, Any] | None, *, summary_file: str = "") -> "PipelineRunResult":
        payload = dict(raw or {})
        summary = PipelineRunSummary.from_raw(payload, summary_file=summary_file)
        payload["items_file"] = summary.items_file
        payload["summary_file"] = summary.summary_file
        payload["promotion_state"] = summary.promotion_state.value
        payload["durability_state"] = summary.durability_state.value
        payload["durably_persisted"] = summary.durably_persisted
        return cls(
            summary=summary,
            data=payload,
            collection_config=dict(payload.get("collection_config") or {}),
            extraction_config=dict(payload.get("extraction_config") or {}),
            validation_failures=list(payload.get("validation_failures") or []),
            extraction_evidence=list(payload.get("extraction_evidence") or []),
            committed_records=list(payload.get("committed_records") or []),
            error=str(payload.get("error") or ""),
        )

    def to_payload(self) -> dict[str, Any]:
        payload = dict(self.data)
        payload.update(
            {
                "total_urls": self.summary.total_urls,
                "success_count": self.summary.success_count,
                "failed_count": self.summary.failed_count,
                "success_rate": self.summary.success_rate,
                "required_field_success_rate": self.summary.required_field_success_rate,
                "validation_failure_count": self.summary.validation_failure_count,
                "execution_state": self.summary.execution_state,
                "outcome_state": self.summary.outcome_state,
                "terminal_reason": self.summary.terminal_reason,
                "promotion_state": self.summary.promotion_state.value,
                "items_file": self.summary.items_file,
                "summary_file": self.summary.summary_file,
                "execution_id": self.summary.execution_id,
                "durability_state": self.summary.durability_state.value,
                "durably_persisted": self.summary.durably_persisted,
                "collection_config": dict(self.collection_config),
                "extraction_config": dict(self.extraction_config),
                "validation_failures": list(self.validation_failures),
                "extraction_evidence": list(self.extraction_evidence),
                "committed_records": list(self.committed_records),
                "error": self.error,
            }
        )
        return payload


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
class TaskIdentity:
    list_url: str
    anchor_url: str = ""
    page_state_signature: str = ""
    variant_label: str = ""
    task_description: str = ""
    semantic_signature: str = ""
    strategy_payload: dict[str, Any] = field(default_factory=dict)
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
    decision_context: dict[str, Any] = field(default_factory=dict)
    world_snapshot: dict[str, Any] = field(default_factory=dict)
    failure_records: tuple[dict[str, Any], ...] = ()


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
