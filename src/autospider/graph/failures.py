"""Failure classification helpers for graph runtime and contracts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

CONTRACT_VIOLATION_CATEGORY = "contract_violation"
SYSTEM_FAILURE_CATEGORY = "system_failure"
INVALID_PROTOCOL_DETAIL = "invalid_protocol_message"


def _snake_case(name: str) -> str:
    normalized = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", normalized)
    return normalized.strip().lower()


def _build_failure_record(
    *,
    category: str,
    detail: str,
    component: str,
    page_id: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(metadata or {})
    payload["component"] = str(component or "")
    return {
        "page_id": str(page_id or ""),
        "category": str(category or ""),
        "detail": str(detail or ""),
        "metadata": payload,
    }


def classify_protocol_violation(
    *,
    component: str,
    diagnostics: Mapping[str, Any] | None,
    page_id: str = "",
) -> dict[str, Any]:
    payload = dict(diagnostics or {})
    metadata = {
        "action": str(payload.get("action") or ""),
        "response_text": str(payload.get("response_text") or ""),
        "raw_payload": payload.get("raw_payload"),
        "validation_errors": [str(item) for item in list(payload.get("validation_errors") or [])],
    }
    return _build_failure_record(
        category=CONTRACT_VIOLATION_CATEGORY,
        detail=INVALID_PROTOCOL_DETAIL,
        component=component,
        page_id=page_id,
        metadata=metadata,
    )


def classify_runtime_exception(
    *,
    component: str,
    error: BaseException,
    page_id: str = "",
) -> dict[str, Any]:
    metadata = {
        "exception_type": type(error).__name__,
        "message": str(error),
    }
    return _build_failure_record(
        category=SYSTEM_FAILURE_CATEGORY,
        detail=_snake_case(type(error).__name__),
        component=component,
        page_id=page_id,
        metadata=metadata,
    )
