from __future__ import annotations

import json
from pathlib import Path
from typing import Any


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
