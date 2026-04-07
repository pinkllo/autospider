"""Execution-time contracts for the main pipeline path."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


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


class PromotionState(str, Enum):
    REUSABLE = "reusable"
    DIAGNOSTIC_ONLY = "diagnostic_only"
    REJECTED = "rejected"


class DurabilityState(str, Enum):
    DURABLE = "durable"
    NOT_DURABLE = "not_durable"


class AggregationEligibility(str, Enum):
    INCLUDED = "included"
    EXCLUDED = "excluded"
    FAILED = "failed"


class ExecutionRequest(BaseModel):
    """Single normalized request contract for graph/services/pipeline."""

    list_url: str = ""
    site_url: str = ""
    request: str = ""
    task_description: str = ""
    fields: list[dict[str, Any]] = Field(default_factory=list)
    output_dir: str = "output"
    headless: bool | None = None
    field_explore_count: int | None = None
    field_validate_count: int | None = None
    consumer_concurrency: int | None = None
    max_pages: int | None = None
    target_url_count: int | None = None
    pipeline_mode: str | None = None
    guard_intervention_mode: str = "interrupt"
    guard_thread_id: str = ""
    selected_skills: list[dict[str, str]] = Field(default_factory=list)
    plan_knowledge: str = ""
    task_plan_snapshot: dict[str, Any] = Field(default_factory=dict)
    plan_journal: list[dict[str, Any]] = Field(default_factory=list)
    initial_nav_steps: list[dict[str, Any]] = Field(default_factory=list)
    anchor_url: str | None = None
    page_state_signature: str = ""
    variant_label: str | None = None
    max_turns: int | None = None
    max_concurrent: int | None = None
    runtime_subtask_max_children: int | None = None
    runtime_subtasks_use_main_model: bool | None = None
    serial_mode: str | None = None

    @classmethod
    def from_params(
        cls,
        params: dict[str, Any],
        *,
        thread_id: str = "",
        guard_intervention_mode: str = "interrupt",
    ) -> "ExecutionRequest":
        payload = dict(params or {})
        headless = _parse_optional_bool(payload["headless"]) if "headless" in payload else None
        task_description = str(payload.get("task_description") or "").strip()
        request = str(payload.get("request") or task_description or "").strip()
        site_url = str(payload.get("site_url") or payload.get("list_url") or "").strip()
        return cls(
            list_url=str(payload.get("list_url") or "").strip(),
            site_url=site_url,
            request=request,
            task_description=task_description,
            fields=list(payload.get("fields") or []),
            output_dir=str(payload.get("output_dir") or "output"),
            headless=headless,
            field_explore_count=payload.get("field_explore_count"),
            field_validate_count=payload.get("field_validate_count"),
            consumer_concurrency=payload.get("consumer_concurrency"),
            max_pages=payload.get("max_pages"),
            target_url_count=payload.get("target_url_count"),
            pipeline_mode=payload.get("pipeline_mode"),
            guard_intervention_mode=guard_intervention_mode,
            guard_thread_id=thread_id,
            selected_skills=list(payload.get("selected_skills") or []),
            plan_knowledge=str(payload.get("plan_knowledge") or ""),
            task_plan_snapshot=dict(payload.get("task_plan_snapshot") or {}),
            plan_journal=list(payload.get("plan_journal") or []),
            initial_nav_steps=list(payload.get("initial_nav_steps") or []),
            anchor_url=payload.get("anchor_url"),
            page_state_signature=str(payload.get("page_state_signature") or ""),
            variant_label=payload.get("variant_label"),
            max_turns=payload.get("max_turns"),
            max_concurrent=payload.get("max_concurrent"),
            runtime_subtask_max_children=payload.get("runtime_subtask_max_children"),
            runtime_subtasks_use_main_model=payload.get("runtime_subtasks_use_main_model"),
            serial_mode=payload.get("serial_mode"),
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
    promotion_state: PromotionState = PromotionState.REJECTED
    items_file: str = ""
    summary_file: str = ""
    execution_id: str = ""
    durably_persisted: bool = False

    @classmethod
    def from_raw(cls, raw: dict[str, Any], *, summary_file: str = "") -> "PipelineRunSummary":
        promotion = str(raw.get("promotion_state") or PromotionState.REJECTED.value).strip().lower()
        return cls(
            total_urls=int(raw.get("total_urls", 0) or 0),
            success_count=int(raw.get("success_count", 0) or 0),
            failed_count=int(raw.get("failed_count", 0) or 0),
            success_rate=float(raw.get("success_rate", 0.0) or 0.0),
            required_field_success_rate=float(raw.get("required_field_success_rate", 0.0) or 0.0),
            validation_failure_count=int(raw.get("validation_failure_count", 0) or 0),
            execution_state=str(raw.get("execution_state") or ""),
            outcome_state=str(raw.get("outcome_state") or ""),
            promotion_state=PromotionState(promotion),
            items_file=str(raw.get("items_file") or ""),
            summary_file=str(summary_file or raw.get("summary_file") or ""),
            execution_id=str(raw.get("execution_id") or ""),
            durably_persisted=bool(raw.get("durably_persisted")),
        )


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
    items: int = 0
    result_file: str = ""


class AggregationReport(BaseModel):
    merged_items: int = 0
    unique_urls: int = 0
    eligible_subtasks: int = 0
    excluded_subtasks: int = 0
    failed_subtasks: int = 0
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
