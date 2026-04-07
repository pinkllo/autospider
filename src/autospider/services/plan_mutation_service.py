"""Plan mutation service for runtime expand requests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from ..crawler.planner.planner_artifacts import PlannerArtifacts
from ..domain.planning import PlanJournalEntry, SubTask, TaskPlan


@dataclass(frozen=True, slots=True)
class PlanMutationResult:
    task_plan: TaskPlan
    dispatch_queue: tuple[dict[str, Any], ...]
    plan_knowledge: str


class PlanMutationService:
    """The only component allowed to merge runtime expand requests into a plan."""

    def __init__(
        self,
        *,
        artifact_factory: Callable[..., PlannerArtifacts] = PlannerArtifacts,
    ) -> None:
        self._artifact_factory = artifact_factory

    def merge_expand_requests(
        self,
        *,
        plan: TaskPlan,
        expand_requests: list[dict[str, Any]],
        pending_queue: list[dict[str, Any]],
        output_dir: str,
    ) -> PlanMutationResult:
        queue = list(pending_queue)
        known = {self._signature(subtask.model_dump(mode="python")) for subtask in plan.subtasks}
        self._merge_journal_entries(plan, expand_requests)
        for raw_request in expand_requests:
            for raw_subtask in list(raw_request.get("spawned_subtasks") or []):
                candidate = self._inherit_parent_nav_steps(raw_subtask, plan)
                signature = self._signature(candidate)
                if signature in known:
                    continue
                known.add(signature)
                plan.subtasks.append(SubTask.model_validate(candidate))
                queue.append(candidate)

        artifacts = self._artifact_factory(
            site_url=str(plan.site_url or ""),
            user_request=str(plan.original_request or ""),
            output_dir=output_dir,
        )
        plan.updated_at = datetime.now().isoformat(timespec="seconds")
        persisted_plan = artifacts.save_plan(plan)
        return PlanMutationResult(
            task_plan=persisted_plan,
            dispatch_queue=tuple(queue),
            plan_knowledge=artifacts.build_knowledge_doc(persisted_plan),
        )

    @staticmethod
    def _signature(payload: dict[str, Any]) -> tuple[str, str, str, str, str]:
        return (
            str(payload.get("page_state_signature") or "").strip(),
            str(payload.get("anchor_url") or "").strip(),
            str(payload.get("variant_label") or "").strip(),
            str(payload.get("task_description") or "").strip(),
            str(payload.get("parent_id") or "").strip(),
        )

    @staticmethod
    def _inherit_parent_nav_steps(payload: dict[str, Any], plan: TaskPlan) -> dict[str, Any]:
        hydrated = dict(payload or {})
        if hydrated.get("nav_steps"):
            return hydrated
        parent_id = str(hydrated.get("parent_id") or "").strip()
        if not parent_id:
            return hydrated
        for subtask in plan.subtasks:
            if subtask.id == parent_id:
                hydrated["nav_steps"] = list(subtask.nav_steps or [])
                return hydrated
        return hydrated

    @staticmethod
    def _merge_journal_entries(plan: TaskPlan, expand_requests: list[dict[str, Any]]) -> None:
        existing = {
            (
                str(entry.entry_id or ""),
                str(entry.phase or ""),
                str(entry.action or ""),
                str(entry.created_at or ""),
            )
            for entry in list(plan.journal or [])
        }
        for raw_request in expand_requests:
            for raw_entry in list(raw_request.get("journal_entries") or []):
                entry = dict(raw_entry or {})
                entry.setdefault("entry_id", f"runtime_{datetime.now().strftime('%H%M%S%f')}")
                entry.setdefault("created_at", datetime.now().isoformat(timespec="seconds"))
                key = (
                    str(entry.get("entry_id") or ""),
                    str(entry.get("phase") or ""),
                    str(entry.get("action") or ""),
                    str(entry.get("created_at") or ""),
                )
                if key in existing:
                    continue
                existing.add(key)
                plan.journal.append(PlanJournalEntry.model_validate(entry))
