"""共享收敛节点。"""

from __future__ import annotations

from typing import Any


def _dedupe_artifacts(artifacts: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    merged: list[dict[str, str]] = []
    for item in artifacts:
        label = str(item.get("label") or "")
        path = str(item.get("path") or "")
        key = (label, path)
        if not path or key in seen:
            continue
        seen.add(key)
        merged.append({"label": label, "path": path})
    return merged


def build_artifact_index(state: dict[str, Any]) -> dict[str, Any]:
    """聚合节点产物。"""
    artifacts = list(state.get("artifacts") or [])
    artifacts.extend(list(state.get("node_artifacts") or []))
    return {"artifacts": _dedupe_artifacts(artifacts)}


def build_summary(state: dict[str, Any]) -> dict[str, Any]:
    """构建统一摘要。"""
    summary = dict(state.get("summary") or {})
    if not summary:
        payload = dict(state.get("node_payload") or {})
        summary = dict(payload.get("result") or {})
    summary["request_id"] = str(state.get("request_id") or "")
    summary["entry_mode"] = str(state.get("entry_mode") or "")
    return {"summary": summary}


def finalize_result(state: dict[str, Any]) -> dict[str, Any]:
    """结束节点：写入统一状态字段。"""
    error_code = str(state.get("error_code") or "")
    error_message = str(state.get("error_message") or "")
    node_error = state.get("node_error") or {}

    if not error_code and isinstance(node_error, dict):
        error_code = str(node_error.get("code") or "")
        error_message = str(node_error.get("message") or "")

    status = "success"
    if error_code:
        status = "failed"
    else:
        summary = dict(state.get("summary") or {})
        failed = int(summary.get("failed", 0) or 0)
        completed = int(summary.get("completed", 0) or 0)
        if failed > 0 and completed > 0:
            status = "partial_success"
        elif failed > 0:
            status = "failed"

    return {
        "status": status,
        "error_code": error_code,
        "error_message": error_message,
    }
