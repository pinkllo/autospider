from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from autospider.common.storage.idempotent_io import load_json_if_exists, write_json_idempotent
from autospider.contexts.planning.domain.model import PlanJournalEntry, PlanNode, SubTask, TaskPlan


class ArtifactPlanRepository:
    def __init__(self, *, site_url: str, user_request: str, output_dir: str) -> None:
        self._site_url = site_url
        self._user_request = user_request
        self._output_dir = Path(output_dir)

    def build_plan(
        self,
        subtasks: list[SubTask],
        *,
        nodes: list[PlanNode] | None = None,
        journal: list[PlanJournalEntry] | None = None,
    ) -> TaskPlan:
        existing = self._load_saved_plan()
        created_at = existing.created_at if existing else datetime.now(UTC).isoformat()
        updated_at = datetime.now(UTC).isoformat()
        return TaskPlan(
            plan_id=existing.plan_id if existing else self._build_plan_id(),
            original_request=self._user_request,
            site_url=self._site_url,
            subtasks=list(subtasks),
            nodes=list(nodes or []),
            journal=list(journal or []),
            total_subtasks=len(subtasks),
            created_at=created_at,
            updated_at=updated_at,
        )

    def create_empty_plan(self) -> TaskPlan:
        return self.build_plan([])

    def save_plan(self, plan: TaskPlan) -> TaskPlan:
        self._output_dir.mkdir(parents=True, exist_ok=True)
        persisted = write_json_idempotent(
            self._output_dir / "task_plan.json",
            plan.model_dump(mode="python"),
            identity_keys=("site_url", "original_request", "plan_id"),
        )
        return TaskPlan.model_validate(persisted)

    def _build_plan_id(self) -> str:
        payload = json.dumps(
            {"site_url": self._site_url, "user_request": self._user_request},
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]

    def _load_saved_plan(self) -> TaskPlan | None:
        data = load_json_if_exists(self._output_dir / "task_plan.json")
        if not isinstance(data, dict):
            return None
        if str(data.get("site_url") or "") != self._site_url:
            return None
        if str(data.get("original_request") or "") != self._user_request:
            return None
        try:
            return TaskPlan.model_validate(data)
        except Exception:
            return None
