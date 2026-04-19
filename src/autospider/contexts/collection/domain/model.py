from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from autospider.contexts.collection.domain.field.model import FieldBinding


def _text(value: Any) -> str:
    return str(value or "").strip()


@dataclass(frozen=True, slots=True)
class PageResult:
    url: str
    status: str
    fields: dict[str, str] = field(default_factory=dict)
    error_kind: str = ""
    error_message: str = ""
    duration_ms: int = 0

    def to_payload(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "status": self.status,
            "fields": dict(self.fields),
            "error_kind": self.error_kind,
            "error_message": self.error_message,
            "duration_ms": self.duration_ms,
        }


@dataclass(frozen=True, slots=True)
class CollectionRun:
    run_id: str
    plan_id: str
    subtask_id: str
    thread_id: str
    status: str = "running"
    pages: tuple[PageResult, ...] = ()
    bindings: tuple[FieldBinding, ...] = ()
    artifacts_dir: str = ""

    def summarize(self) -> dict[str, Any]:
        success_count = sum(1 for item in self.pages if item.status == "succeeded")
        failure_count = sum(1 for item in self.pages if item.status == "failed")
        return {
            "run_id": self.run_id,
            "plan_id": self.plan_id,
            "subtask_id": self.subtask_id,
            "status": self.status,
            "total_urls": len(self.pages),
            "success_count": success_count,
            "failure_count": failure_count,
            "artifacts_dir": _text(self.artifacts_dir),
        }
