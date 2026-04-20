from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

PublicEntryMode = Literal["chat_pipeline"]
EntryMode = PublicEntryMode

NodeStatus = Literal["ok", "retryable", "fatal"]
GraphStatus = Literal["success", "partial_success", "failed", "no_data", "interrupted"]


class GraphError(BaseModel):
    code: str
    message: str


class GraphInput(BaseModel):
    entry_mode: EntryMode = Field(
        ...,
        description="正式公开入口仅支持 chat_pipeline。",
    )
    cli_args: dict[str, Any] = Field(default_factory=dict)
    request_id: str = Field(default="")
    invoked_at: str = Field(default="")
    thread_id: str = Field(default_factory=lambda: uuid4().hex)


class NodeResult(BaseModel):
    node_status: NodeStatus
    node_payload: dict[str, Any] = Field(default_factory=dict)
    node_artifacts: list[dict[str, str]] = Field(default_factory=list)
    node_error: GraphError | None = None


class GraphResult(BaseModel):
    status: GraphStatus
    entry_mode: EntryMode
    summary: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[dict[str, str]] = Field(default_factory=list)
    error: GraphError | None = None
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="稳定的 result_context 结果载荷。",
    )
    thread_id: str = ""
    checkpoint_id: str = ""
    next_nodes: list[str] = Field(default_factory=list)
    interrupts: list[dict[str, Any]] = Field(default_factory=list)


GraphInput.model_rebuild()
NodeResult.model_rebuild()
GraphResult.model_rebuild()
