from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_STAGED_WRITES: dict[str, str] = {}


def build_task_plan(page_url: str, task_description: str) -> dict[str, Any]:
    return {
        "plan_id": "contract-plan-001",
        "site_url": page_url,
        "original_request": task_description,
        "total_subtasks": 1,
        "subtasks": [{"name": "detail", "list_url": page_url}],
    }


async def persist_snapshot(
    *,
    output_dir: str,
    plan_knowledge: str = "",
    task_plan: dict[str, Any] | None = None,
    **_: Any,
) -> None:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    plan = build_task_plan(str((task_plan or {}).get("site_url") or ""), str((task_plan or {}).get("original_request") or ""))
    (output_path / "task_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_path / "plan_knowledge.md").write_text(str(plan_knowledge or ""), encoding="utf-8")


def prepare_output(*, output_path: Path, items_path: Path, summary_path: Path) -> None:
    output_path.mkdir(parents=True, exist_ok=True)
    _STAGED_WRITES.pop(str(items_path), None)
    _STAGED_WRITES.pop(str(summary_path), None)
    items_path.unlink(missing_ok=True)
    summary_path.unlink(missing_ok=True)


def commit_items_file(items_path: Path, records: dict[str, dict[str, Any]]) -> None:
    items_path.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        json.dumps(record["item"], ensure_ascii=False)
        for _, record in sorted(records.items())
        if record.get("success") and record.get("durability_state") == "durable"
    ]
    content = "\n".join(payload) + ("\n" if payload else "")
    _STAGED_WRITES[str(items_path)] = content
    items_path.write_text(content, encoding="utf-8")


def write_summary(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(summary, ensure_ascii=False, indent=2)
    _STAGED_WRITES[str(path)] = content
    path.write_text(content, encoding="utf-8")


def promote_output(staging_path: Path, final_path: Path) -> None:
    final_path.parent.mkdir(parents=True, exist_ok=True)
    content = _STAGED_WRITES.get(str(staging_path))
    if content is not None:
        final_path.write_text(content, encoding="utf-8")
        staging_path.unlink(missing_ok=True)
        return
    staging_path.replace(final_path)


def materialize_output(
    *,
    output_dir: Path,
    result_payload: dict[str, Any],
    records: dict[str, dict[str, Any]],
    page_url: str,
    task_description: str,
    plan_knowledge: str,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    items_path = output_dir / "pipeline_extracted_items.jsonl"
    summary_path = output_dir / "pipeline_summary.json"
    task_plan_path = output_dir / "task_plan.json"
    knowledge_path = output_dir / "plan_knowledge.md"
    commit_items_file(items_path, records)
    write_summary(summary_path, result_payload)
    task_plan_path.write_text(
        json.dumps(build_task_plan(page_url, task_description), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    knowledge_path.write_text(plan_knowledge, encoding="utf-8")
