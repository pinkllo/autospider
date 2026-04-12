"""共享收敛节点。"""

from __future__ import annotations

from typing import Any

from ..state_access import dispatch_state, get_error_state, get_result_artifacts, get_result_state, get_result_summary
from ..workflow_access import coerce_workflow_state


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
    artifacts = get_result_artifacts(state)
    artifacts.extend(list(state.get("node_artifacts") or []))
    deduped = _dedupe_artifacts(artifacts)
    result = get_result_state(state)
    result["artifacts"] = deduped
    return {"artifacts": deduped, "result": result}


def build_summary(state: dict[str, Any]) -> dict[str, Any]:
    """构建统一摘要。"""
    result = get_result_state(state)
    summary = get_result_summary(state)
    dispatch = dispatch_state(state)
    if dispatch and not summary:
        summary = dict(dispatch.get("summary") or {})
    meta = dict(coerce_workflow_state(state).get("meta") or {})
    summary["thread_id"] = str(meta.get("thread_id") or state.get("thread_id") or "")
    summary["request_id"] = str(meta.get("request_id") or state.get("request_id") or "")
    summary["entry_mode"] = str(meta.get("entry_mode") or state.get("entry_mode") or "")
    result["summary"] = summary
    return {"result": result}


def _resolve_summary_outcome_state(summary: dict[str, Any]) -> str:
    outcome_state = str(summary.get("outcome_state") or "").strip().lower()
    if outcome_state in {"success", "partial_success", "failed", "no_data"}:
        return outcome_state
    if outcome_state == "system_failure":
        return "failed"

    failed = int(summary.get("failed", 0) or summary.get("failed_count", 0) or 0)
    completed = int(summary.get("completed", 0) or summary.get("success_count", 0) or 0)
    no_data = int(summary.get("no_data", 0) or 0)
    if failed > 0 and completed > 0:
        return "partial_success"
    if failed > 0:
        return "failed"
    if no_data > 0 and completed <= 0:
        return "no_data"
    return "success"

def finalize_result(state: dict[str, Any]) -> dict[str, Any]:
    """结束节点：写入统一状态字段。"""
    error = get_error_state(state)
    error_code = str(error.get("code") or "")
    error_message = str(error.get("message") or "")
    result = get_result_state(state)
    status = str(result.get("status") or "").strip().lower()
    if error_code:
        status = "failed"
    elif status not in {"success", "partial_success", "failed", "no_data", "interrupted"}:
        status = _resolve_summary_outcome_state(get_result_summary(state))

    return {
        "status": status,
        "error_code": error_code,
        "error_message": error_message,
        "error": {"code": error_code, "message": error_message} if error_code else None,
        "result": {**result, "status": status},
    }
