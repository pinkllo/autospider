from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


def _text(value: Any) -> str:
    return str(value or "").strip()


def _string_map(value: object, *, drop_empty: bool = True) -> dict[str, str]:
    normalized: dict[str, str] = {}
    if not isinstance(value, Mapping):
        return normalized
    for key, item in value.items():
        text_key = _text(key)
        text_value = "true" if item is True else "false" if item is False else _text(item)
        if not text_key:
            continue
        if drop_empty and not text_value:
            continue
        normalized[text_key] = text_value
    return normalized


def _string_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    items = value if isinstance(value, (list, tuple, set)) else [value]
    return [text for item in items if (text := _text(item))]


def _positive_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _normalize_grouping(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    raw = dict(payload or {})
    group_by = _text(raw.get("group_by")).lower()
    if group_by not in {"none", "category"}:
        group_by = "none"
    mode = _text(raw.get("category_discovery_mode")).lower()
    if mode not in {"auto", "manual"}:
        mode = "auto"
    requested_categories = _string_list(raw.get("requested_categories"))
    if group_by == "none":
        return {
            "group_by": "none",
            "per_group_target_count": None,
            "total_target_count": _positive_int(raw.get("total_target_count")),
            "category_discovery_mode": "auto",
            "requested_categories": [],
            "category_examples": [],
        }
    if mode == "manual" and not requested_categories:
        mode = "auto"
    if mode == "auto":
        requested_categories = []
    return {
        "group_by": group_by,
        "per_group_target_count": _positive_int(raw.get("per_group_target_count")),
        "total_target_count": _positive_int(raw.get("total_target_count")),
        "category_discovery_mode": mode,
        "requested_categories": requested_categories,
        "category_examples": _string_list(raw.get("category_examples")),
    }


class SubTaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    EXPANDED = "expanded"
    COMPLETED = "completed"
    NO_DATA = "no_data"
    BUSINESS_FAILURE = "business_failure"
    SYSTEM_FAILURE = "system_failure"
    SKIPPED = "skipped"


class SubTaskMode(str, Enum):
    EXPAND = "expand"
    COLLECT = "collect"


class PlanNodeType(str, Enum):
    ROOT = "root"
    CATEGORY = "category"
    LIST_PAGE = "list_page"
    STATEFUL_LIST = "stateful_list"
    LEAF = "leaf"


class ExecutionBrief(BaseModel):
    parent_chain: list[str] = Field(default_factory=list)
    current_scope: str = ""
    objective: str = ""
    next_action: str = ""
    stop_rule: str = ""
    do_not: list[str] = Field(default_factory=list)


class PlannerIntent(BaseModel):
    group_by: str = "none"
    per_group_target_count: int | None = None
    total_target_count: int | None = None
    category_discovery_mode: str = "auto"
    requested_categories: list[str] = Field(default_factory=list)
    category_examples: list[str] = Field(default_factory=list)
    subtask_scope_key: str | None = None
    subtask_scope_label: str | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "PlannerIntent":
        return cls.model_validate(_normalize_grouping(payload))


class PlannerCategoryCandidate(BaseModel):
    name: str = ""
    mark_id: int | None = None
    link_text: str = ""
    estimated_pages: int | None = None
    task_description: str = ""
    scope_key: str | None = None
    scope_label: str | None = None


class PlanJournalEntry(BaseModel):
    entry_id: str
    node_id: str | None = None
    phase: str = ""
    action: str = ""
    reason: str = ""
    evidence: str = ""
    metadata: dict[str, str] = Field(default_factory=dict)
    created_at: str = ""

    @field_validator("metadata", mode="before")
    @classmethod
    def _normalize_metadata(cls, value: object) -> dict[str, str]:
        return _string_map(value, drop_empty=False)


class PlanNode(BaseModel):
    node_id: str
    parent_node_id: str | None = None
    name: str
    node_type: PlanNodeType
    url: str = ""
    anchor_url: str | None = None
    page_state_signature: str | None = None
    variant_label: str | None = None
    task_description: str = ""
    observations: str = ""
    depth: int = 0
    nav_steps: list[dict[str, Any]] = Field(default_factory=list)
    context: dict[str, str] = Field(default_factory=dict)
    subtask_id: str | None = None
    is_leaf: bool = False
    executable: bool = False
    children_count: int = 0

    @field_validator("context", mode="before")
    @classmethod
    def _normalize_context(cls, value: object) -> dict[str, str]:
        return _string_map(value, drop_empty=False)


class SubTask(BaseModel):
    id: str
    name: str
    list_url: str
    anchor_url: str | None = None
    page_state_signature: str = ""
    variant_label: str | None = None
    task_description: str
    fields: list[dict[str, Any]] = Field(default_factory=list)
    max_pages: int | None = None
    target_url_count: int | None = None
    per_subtask_target_count: int | None = None
    priority: int = 0
    parent_id: str | None = None
    depth: int = 0
    nav_steps: list[dict[str, Any]] = Field(default_factory=list)
    context: dict[str, str] = Field(default_factory=dict)
    scope: dict[str, Any] = Field(default_factory=dict)
    fixed_fields: dict[str, str] = Field(default_factory=dict)
    mode: SubTaskMode = SubTaskMode.COLLECT
    execution_brief: ExecutionBrief = Field(default_factory=ExecutionBrief)
    plan_node_id: str | None = None
    status: SubTaskStatus = SubTaskStatus.PENDING
    retry_count: int = 0
    error: str | None = None
    result_file: str | None = None
    collected_count: int = 0

    @field_validator("context", mode="before")
    @classmethod
    def _normalize_context(cls, value: object) -> dict[str, str]:
        return _string_map(value, drop_empty=False)

    @field_validator("scope", mode="before")
    @classmethod
    def _normalize_scope(cls, value: object) -> dict[str, Any]:
        return dict(value) if isinstance(value, Mapping) else {}

    @field_validator("fixed_fields", mode="before")
    @classmethod
    def _normalize_fixed_fields(cls, value: object) -> dict[str, str]:
        return _string_map(value, drop_empty=False)


class TaskPlan(BaseModel):
    plan_id: str
    original_request: str
    site_url: str
    subtasks: list[SubTask] = Field(default_factory=list)
    nodes: list[PlanNode] = Field(default_factory=list)
    journal: list[PlanJournalEntry] = Field(default_factory=list)
    total_subtasks: int = 0
    shared_fields: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


def format_execution_brief(brief: ExecutionBrief | dict[str, Any] | None) -> str:
    if brief is None:
        return "无"
    normalized = brief if isinstance(brief, ExecutionBrief) else ExecutionBrief.model_validate(brief)
    parts: list[str] = []
    if normalized.parent_chain:
        parts.append(f"- 父链路: {' > '.join(normalized.parent_chain)}")
    if normalized.current_scope:
        parts.append(f"- 当前作用域: {normalized.current_scope}")
    if normalized.objective:
        parts.append(f"- 目标: {normalized.objective}")
    if normalized.next_action:
        parts.append(f"- 下一步: {normalized.next_action}")
    if normalized.stop_rule:
        parts.append(f"- 停止条件: {normalized.stop_rule}")
    parts.extend(f"- 禁止: {item}" for item in normalized.do_not if _text(item))
    return "\n".join(parts) if parts else "无"
