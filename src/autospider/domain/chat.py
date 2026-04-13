"""聊天澄清领域模型。"""

from __future__ import annotations

from dataclasses import dataclass, field

from .fields import FieldDefinition


@dataclass
class DialogueMessage:
    """单条对话消息。"""

    role: str
    content: str


@dataclass
class ClarifiedTask:
    """澄清后的可执行任务。"""

    intent: str
    list_url: str
    task_description: str
    fields: list[FieldDefinition]
    group_by: str = "none"
    per_group_target_count: int | None = None
    total_target_count: int | None = None
    category_discovery_mode: str = "auto"
    requested_categories: list[str] = field(default_factory=list)
    category_examples: list[str] = field(default_factory=list)
    max_pages: int | None = None
    target_url_count: int | None = None
    consumer_concurrency: int | None = None
    field_explore_count: int | None = None
    field_validate_count: int | None = None


@dataclass
class ClarificationResult:
    """澄清器输出。"""

    status: str
    intent: str
    confidence: float
    next_question: str
    reason: str
    task: ClarifiedTask | None
