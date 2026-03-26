"""共享收敛节点。"""

from __future__ import annotations

from typing import Any

from ...common.logger import get_logger
from ...common.storage.task_registry import TaskRegistry

logger = get_logger(__name__)


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
    summary["thread_id"] = str(state.get("thread_id") or "")
    summary["request_id"] = str(state.get("request_id") or "")
    summary["entry_mode"] = str(state.get("entry_mode") or "")

    # 任务成功完成时注册到历史任务注册表
    _try_register_task(state, summary)

    return {"summary": summary}


def _try_register_task(state: dict[str, Any], summary: dict[str, Any]) -> None:
    """尝试将已完成的任务注册到任务注册表，不影响主流程。"""
    try:
        node_status = str(state.get("node_status") or "")
        if node_status not in {"ok", ""}:
            return

        params = dict(state.get("normalized_params") or state.get("cli_args") or {})
        list_url = str(params.get("list_url") or "")
        task_desc = str(params.get("task_description") or params.get("request") or "")

        if not list_url or not task_desc:
            return

        collected = int(
            summary.get("total_urls", 0)
            or summary.get("collected_urls", 0)
            or summary.get("total_collected", 0)
            or 0
        )
        if collected <= 0:
            return

        output_dir = str(params.get("output_dir") or "output")
        fields = [
            str(f.get("name") or "")
            for f in list(params.get("fields") or [])
            if isinstance(f, dict) and f.get("name")
        ]

        registry = TaskRegistry(registry_path=f"{output_dir}/.task_registry.json")
        registry.register(
            url=list_url,
            task_description=task_desc,
            fields=fields,
            execution_id=str(summary.get("execution_id") or summary.get("run_id") or ""),
            output_dir=output_dir,
            status="completed",
            collected_count=collected,
        )
    except Exception as exc:
        logger.debug("[TaskRegistry] 注册任务失败（不影响主流程）: %s", exc)


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
