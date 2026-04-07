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
    deduped = _dedupe_artifacts(artifacts)
    result = dict(state.get("result") or {})
    result["artifacts"] = deduped
    return {"artifacts": deduped, "result": result}


def build_summary(state: dict[str, Any]) -> dict[str, Any]:
    """构建统一摘要。"""
    result = dict(state.get("result") or {})
    dispatch = dict(state.get("dispatch") or {})
    planning = dict(state.get("planning") or {})
    summary = dict(
        result.get("summary")
        or dispatch.get("summary")
        or planning.get("summary")
        or state.get("summary")
        or {}
    )
    if not summary:
        summary = dict(result.get("data") or {})
    summary["thread_id"] = str(state.get("thread_id") or "")
    summary["request_id"] = str(state.get("request_id") or "")
    summary["entry_mode"] = str(state.get("entry_mode") or "")
    result["summary"] = summary
    return {"summary": summary, "result": result}


def _resolve_summary_outcome_state(summary: dict[str, Any]) -> str:
    outcome_state = str(summary.get("outcome_state") or "").strip().lower()
    if outcome_state in {"success", "partial_success", "failed", "no_data", "system_failure"}:
        return outcome_state

    failed = int(summary.get("failed", 0) or summary.get("failed_count", 0) or 0)
    completed = int(summary.get("completed", 0) or summary.get("success_count", 0) or 0)
    if failed > 0 and completed > 0:
        return "partial_success"
    if failed > 0:
        return "failed"
    return "success"

def finalize_result(state: dict[str, Any]) -> dict[str, Any]:
    """结束节点：写入统一状态字段。"""
    error = dict(state.get("error") or {})
    error_code = str(error.get("code") or state.get("error_code") or "")
    error_message = str(error.get("message") or state.get("error_message") or "")
    node_error = state.get("node_error") or {}

    if not error_code and isinstance(node_error, dict):
        error_code = str(node_error.get("code") or "")
        error_message = str(node_error.get("message") or "")

    result = dict(state.get("result") or {})
    status = str(result.get("status") or "").strip().lower() or "success"
    if error_code:
        status = "failed"
    elif not result.get("status"):
        summary = dict(result.get("summary") or state.get("summary") or {})
        status = _resolve_summary_outcome_state(summary)

    return {
        "status": status,
        "error_code": error_code,
        "error_message": error_message,
        "error": {"code": error_code, "message": error_message} if error_code else None,
        "result": {**result, "status": status},
    }
