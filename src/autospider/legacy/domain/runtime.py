"""运行态领域模型。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SubTaskRuntimeSummary(BaseModel):
    total_urls: int = 0
    success_count: int = 0
    failed_count: int = 0
    success_rate: float = 0.0
    required_field_success_rate: float = 0.0
    validation_failure_count: int = 0
    execution_state: str = ""
    outcome_state: str = ""
    terminal_reason: str = ""
    promotion_state: str = ""
    execution_id: str = ""
    items_file: str = ""
    durability_state: str = ""
    durably_persisted: bool = False
    reliable_for_aggregation: bool = False
    failure_category: str = ""
    failure_detail: str = ""


class SubTaskRuntimeState(BaseModel):
    subtask_id: str
    name: str = ""
    list_url: str = ""
    anchor_url: str = ""
    page_state_signature: str = ""
    variant_label: str = ""
    task_description: str = ""
    mode: str = ""
    execution_brief: dict[str, Any] = Field(default_factory=dict)
    parent_id: str = ""
    depth: int = 0
    context: dict[str, str] = Field(default_factory=dict)
    status: str = ""
    outcome_type: str = ""
    error: str = ""
    retry_count: int = 0
    result_file: str = ""
    collected_count: int = 0
    summary: SubTaskRuntimeSummary = Field(default_factory=SubTaskRuntimeSummary)
    collection_config: dict[str, Any] = Field(default_factory=dict)
    extraction_config: dict[str, Any] = Field(default_factory=dict)
    extraction_evidence: list[dict[str, Any]] = Field(default_factory=list)
    validation_failures: list[dict[str, Any]] = Field(default_factory=list)
    journal_entries: list[dict[str, Any]] = Field(default_factory=list)
    expand_request: dict[str, Any] = Field(default_factory=dict)
