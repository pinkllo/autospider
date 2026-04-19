from __future__ import annotations

from datetime import datetime
from typing import Any

from autospider.contexts.planning.domain import PlanJournalEntry, PlanNode, PlanNodeType, SubTask, SubTaskMode


class PlannerPlanRecordsMixin:
    def _record_planning_dead_end(
        self,
        *,
        entry_index: int,
        node_id: str,
        reason: str,
        evidence: str,
        metadata: dict[str, str] | None = None,
    ) -> None:
        self._knowledge_entries[entry_index]["children_count"] = 0
        self._knowledge_entries[entry_index]["is_leaf"] = False
        self._knowledge_entries[entry_index]["executable"] = False
        self._append_journal(
            node_id=node_id,
            phase="planning",
            action="planning_dead_end",
            reason=reason,
            evidence=evidence,
            metadata=dict(metadata or {}),
        )

    def _record_planned_subtask_node(
        self,
        *,
        subtask: SubTask,
        parent_node_id: str | None,
        reason: str,
    ) -> None:
        node_id = self._next_node_id()
        self._knowledge_entries.append(
            {
                "node_id": node_id,
                "parent_node_id": parent_node_id,
                "depth": int(subtask.depth or 0),
                "url": subtask.list_url,
                "anchor_url": subtask.anchor_url or subtask.list_url,
                "page_state_signature": subtask.page_state_signature,
                "variant_label": subtask.variant_label,
                "page_type": "list_page" if subtask.mode == SubTaskMode.COLLECT else "category",
                "name": subtask.name,
                "observations": "",
                "children_count": 0,
                "is_leaf": subtask.mode == SubTaskMode.COLLECT,
                "task_description": subtask.task_description,
                "context": dict(subtask.context or {}),
                "nav_steps": list(subtask.nav_steps or []),
                "subtask_id": subtask.id,
                "executable": True,
                "node_type": self._resolve_subtask_node_type(subtask),
            }
        )
        self._append_journal(
            node_id=node_id,
            phase="planning",
            action="create_subtask",
            reason=reason,
            evidence=subtask.task_description,
            metadata={
                "subtask_id": subtask.id,
                "mode": subtask.mode.value,
                "page_state_signature": str(subtask.page_state_signature or ""),
            },
        )

    def _resolve_subtask_node_type(self, subtask: SubTask) -> str:
        if subtask.mode != SubTaskMode.COLLECT:
            return PlanNodeType.CATEGORY.value
        if list(subtask.nav_steps or []):
            return PlanNodeType.STATEFUL_LIST.value
        return PlanNodeType.LEAF.value

    def _build_plan(self, subtasks: list[SubTask]):
        return self._artifacts.build_plan(
            subtasks,
            nodes=self._build_plan_nodes(),
            journal=self._build_plan_journal(),
        )

    def _build_plan_id(self) -> str:
        return self._artifacts._build_plan_id()

    def _load_saved_plan(self):
        return self._artifacts._load_saved_plan()

    def _create_empty_plan(self):
        return self._artifacts.create_empty_plan()

    def _save_plan(self, plan):
        return self._artifacts.save_plan(plan)

    def _write_knowledge_doc(self, plan) -> None:
        self._artifacts.write_knowledge_doc(plan)

    def render_plan_knowledge(self, plan) -> str:
        return self._artifacts.build_knowledge_doc(plan)

    def _sediment_draft_skill(self, plan) -> None:
        self._artifacts.sediment_draft_skill(plan)

    def _build_plan_nodes(self) -> list[PlanNode]:
        nodes: list[PlanNode] = []
        for raw in self._knowledge_entries:
            node_type = self._resolve_plan_node_type(raw)
            nodes.append(
                PlanNode(
                    node_id=str(raw.get("node_id") or ""),
                    parent_node_id=str(raw.get("parent_node_id") or "") or None,
                    name=str(raw.get("name") or ""),
                    node_type=node_type,
                    url=str(raw.get("url") or ""),
                    anchor_url=str(raw.get("anchor_url") or "") or None,
                    page_state_signature=str(raw.get("page_state_signature") or "") or None,
                    variant_label=str(raw.get("variant_label") or "") or None,
                    task_description=str(raw.get("task_description") or ""),
                    observations=str(raw.get("observations") or ""),
                    depth=int(raw.get("depth", 0) or 0),
                    nav_steps=list(raw.get("nav_steps") or []),
                    context=dict(raw.get("context") or {}),
                    subtask_id=str(raw.get("subtask_id") or "") or None,
                    is_leaf=bool(raw.get("is_leaf", False)),
                    executable=bool(raw.get("executable", False)),
                    children_count=int(raw.get("children_count", 0) or 0),
                )
            )
        return nodes

    def _resolve_plan_node_type(self, raw: dict[str, Any]) -> PlanNodeType:
        raw_type = str(raw.get("node_type") or raw.get("page_type") or "").strip()
        if raw.get("is_leaf") and raw_type not in {PlanNodeType.STATEFUL_LIST.value, PlanNodeType.LEAF.value}:
            return PlanNodeType.LEAF
        try:
            return PlanNodeType(raw_type)
        except ValueError:
            if raw.get("is_leaf"):
                return PlanNodeType.LEAF
            return PlanNodeType.CATEGORY

    def _build_plan_journal(self) -> list[PlanJournalEntry]:
        entries: list[PlanJournalEntry] = []
        for raw in self._journal_entries:
            entries.append(
                PlanJournalEntry(
                    entry_id=str(raw.get("entry_id") or ""),
                    node_id=str(raw.get("node_id") or "") or None,
                    phase=str(raw.get("phase") or ""),
                    action=str(raw.get("action") or ""),
                    reason=str(raw.get("reason") or ""),
                    evidence=str(raw.get("evidence") or ""),
                    metadata={str(k): str(v) for k, v in dict(raw.get("metadata") or {}).items()},
                    created_at=str(raw.get("created_at") or ""),
                )
            )
        return entries

    def _append_journal(
        self,
        *,
        node_id: str | None,
        phase: str,
        action: str,
        reason: str,
        evidence: str = "",
        metadata: dict[str, str] | None = None,
    ) -> None:
        self._journal_entries.append(
            {
                "entry_id": self._next_journal_id(),
                "node_id": node_id,
                "phase": phase,
                "action": action,
                "reason": reason,
                "evidence": evidence,
                "metadata": dict(metadata or {}),
                "created_at": datetime.now().isoformat(timespec="seconds"),
            }
        )

    def _next_node_id(self) -> str:
        return f"node_{len(self._knowledge_entries) + 1:03d}"

    def _next_journal_id(self) -> str:
        return f"journal_{len(self._journal_entries) + 1:04d}"
