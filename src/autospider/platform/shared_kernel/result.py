from __future__ import annotations

from pathlib import Path
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")
ResultStatus = Literal["success", "partial", "failed"]


class ErrorInfo(BaseModel):
    kind: str
    code: str
    message: str
    context: dict[str, str] = Field(default_factory=dict)


class ResultEnvelope(BaseModel, Generic[T]):
    status: ResultStatus
    data: T | None = None
    errors: list[ErrorInfo] = Field(default_factory=list)
    metrics: dict[str, float] = Field(default_factory=dict)
    artifacts_path: Path | None = None
    run_id: str | None = None
    trace_id: str

    @classmethod
    def success(
        cls,
        *,
        data: T,
        trace_id: str,
        run_id: str | None = None,
        metrics: dict[str, float] | None = None,
        artifacts_path: Path | None = None,
    ) -> "ResultEnvelope[T]":
        return cls(
            status="success",
            data=data,
            trace_id=trace_id,
            run_id=run_id,
            metrics=dict(metrics or {}),
            artifacts_path=artifacts_path,
        )

    @classmethod
    def partial(
        cls,
        *,
        data: T | None,
        trace_id: str,
        errors: list[ErrorInfo],
        run_id: str | None = None,
        metrics: dict[str, float] | None = None,
        artifacts_path: Path | None = None,
    ) -> "ResultEnvelope[T]":
        return cls(
            status="partial",
            data=data,
            errors=list(errors),
            trace_id=trace_id,
            run_id=run_id,
            metrics=dict(metrics or {}),
            artifacts_path=artifacts_path,
        )

    @classmethod
    def failed(
        cls,
        *,
        trace_id: str,
        errors: list[ErrorInfo],
        run_id: str | None = None,
        metrics: dict[str, float] | None = None,
        artifacts_path: Path | None = None,
    ) -> "ResultEnvelope[T]":
        return cls(
            status="failed",
            trace_id=trace_id,
            errors=list(errors),
            run_id=run_id,
            metrics=dict(metrics or {}),
            artifacts_path=artifacts_path,
        )
