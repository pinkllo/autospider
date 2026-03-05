"""LangGraph 编排层类型定义。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

EntryMode = Literal[
    "chat_pipeline",
    "pipeline_run",
    "collect_urls",
    "generate_config",
    "batch_collect",
    "field_extract",
    "multi_pipeline",
]

NodeStatus = Literal["ok", "retryable", "fatal"]
GraphStatus = Literal["success", "partial_success", "failed"]


class GraphError(BaseModel):
    """图执行错误。"""

    code: str
    message: str


class GraphInput(BaseModel):
    """图执行输入。"""

    entry_mode: EntryMode
    cli_args: dict[str, Any] = Field(default_factory=dict)
    request_id: str = Field(default_factory=lambda: uuid4().hex)
    invoked_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class NodeResult(BaseModel):
    """节点标准输出。"""

    node_status: NodeStatus
    node_payload: dict[str, Any] = Field(default_factory=dict)
    node_artifacts: list[dict[str, str]] = Field(default_factory=list)
    node_error: GraphError | None = None


class GraphResult(BaseModel):
    """图执行结果。"""

    status: GraphStatus
    entry_mode: EntryMode
    summary: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[dict[str, str]] = Field(default_factory=list)
    error: GraphError | None = None
    data: dict[str, Any] = Field(default_factory=dict)
