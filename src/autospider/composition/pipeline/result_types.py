"""Pipeline result DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class PromotionState(str, Enum):
    REUSABLE = "reusable"
    DIAGNOSTIC_ONLY = "diagnostic_only"
    REJECTED = "rejected"


class DurabilityState(str, Enum):
    STAGED = "staged"
    DURABLE = "durable"
    FAILED_COMMIT = "failed_commit"


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
    failure_category: str = ""
    failure_detail: str = ""

    @classmethod
    def from_raw(cls, raw: dict[str, Any], *, summary_file: str = "") -> "PipelineRunSummary":
        promotion = str(raw.get("promotion_state") or PromotionState.REJECTED.value).strip().lower()
        durability = (
            str(
                raw.get("durability_state")
                or (
                    DurabilityState.DURABLE.value
                    if raw.get("durably_persisted")
                    else DurabilityState.STAGED.value
                )
            )
            .strip()
            .lower()
        )
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
            failure_category=str(raw.get("failure_category") or ""),
            failure_detail=str(raw.get("failure_detail") or ""),
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
                "failure_category": self.summary.failure_category,
                "failure_detail": self.summary.failure_detail,
                "collection_config": dict(self.collection_config),
                "extraction_config": dict(self.extraction_config),
                "validation_failures": list(self.validation_failures),
                "extraction_evidence": list(self.extraction_evidence),
                "committed_records": list(self.committed_records),
                "error": self.error,
            }
        )
        return payload


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
