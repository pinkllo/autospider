"""Planner persistence and knowledge artifact helpers."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from ...common.logger import get_logger
from ...common.storage.idempotent_io import load_json_if_exists, write_json_idempotent
from autospider.contexts.experience.application.skill_promotion import SkillCandidate
from ...contexts.planning.domain import PlanJournalEntry, PlanNode, PlanNodeType, SubTask, TaskPlan

logger = get_logger(__name__)


class PlannerArtifacts:
    """Builds and persists planner outputs without owning traversal logic."""

    def __init__(self, *, site_url: str, user_request: str, output_dir: str) -> None:
        self.site_url = site_url
        self.user_request = user_request
        self.output_dir = output_dir

    def build_plan(
        self,
        subtasks: list[SubTask],
        *,
        nodes: list[PlanNode] | None = None,
        journal: list[PlanJournalEntry] | None = None,
    ) -> TaskPlan:
        existing = self._load_saved_plan()
        created_at = existing.created_at if existing else ""
        updated_at = existing.updated_at if existing else ""

        return TaskPlan(
            plan_id=(existing.plan_id if existing else self._build_plan_id()),
            original_request=self.user_request,
            site_url=self.site_url,
            subtasks=subtasks,
            nodes=list(nodes or []),
            journal=list(journal or []),
            total_subtasks=len(subtasks),
            created_at=created_at,
            updated_at=updated_at,
        )

    def create_empty_plan(self) -> TaskPlan:
        return self.build_plan([])

    def save_plan(self, plan: TaskPlan) -> TaskPlan:
        output_path = Path(self.output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        plan_file = output_path / "task_plan.json"

        persisted = write_json_idempotent(
            plan_file,
            plan.model_dump(mode="python"),
            identity_keys=("site_url", "original_request", "plan_id"),
        )
        logger.info("[Planner] 任务计划已成功持久化至: %s", plan_file)
        return TaskPlan.model_validate(persisted)

    def write_knowledge_doc(self, plan: TaskPlan) -> None:
        content = self.build_knowledge_doc(plan)
        if not content:
            return

        doc_path = Path(self.output_dir) / "plan_knowledge.md"
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text(content, encoding="utf-8")
        logger.info("[Planner] 知识文档已写入: %s", doc_path)

    def build_knowledge_doc(self, plan: TaskPlan) -> str:
        if not plan.nodes and not plan.subtasks:
            return ""

        domain = urlparse(self.site_url).netloc
        leaf_count = sum(1 for node in plan.nodes if node.is_leaf) or len(plan.subtasks)

        lines: list[str] = []
        lines.append(f"# 采集计划: {domain}")
        lines.append("")
        lines.append("## 站点概况")
        lines.append(f"- URL: {self.site_url}")
        lines.append(f"- 需求: {self.user_request}")
        lines.append(f"- 发现时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"- 叶子任务数: {leaf_count}")
        lines.append("")
        lines.append("## 发现过程")
        lines.append("")
        if plan.nodes:
            lines.extend(self._render_nodes(plan))
        else:
            lines.extend(self._render_subtasks(plan))

        return "\n".join(lines)

    def sediment_draft_skill(self, plan: TaskPlan) -> None:
        if not plan.nodes and not plan.subtasks:
            return

        try:
            domain = urlparse(self.site_url).netloc
            output_path = Path(self.output_dir)
            output_path.mkdir(parents=True, exist_ok=True)
            draft_path = output_path / "draft_skill_candidate.json"
            subtask_names = [subtask.name for subtask in plan.subtasks]
            candidate = SkillCandidate(
                domain=domain,
                list_url=self.site_url,
                task_description=self.user_request,
                status="draft",
                summary={"success_count": 0, "total_urls": 0},
                collection_config={
                    "list_url": self.site_url,
                    "anchor_url": self.site_url,
                },
                extraction_config={"fields": []},
                validation_failures=[],
                plan_knowledge=self.build_knowledge_doc(plan),
                subtask_names=subtask_names,
                source="planner",
            )
            write_json_idempotent(
                draft_path,
                {
                    "candidate": candidate.__dict__,
                    "plan_id": str(plan.plan_id or ""),
                    "site_url": self.site_url,
                    "user_request": self.user_request,
                },
                identity_keys=("site_url", "user_request", "plan_id"),
            )
            logger.info("[Planner] Draft skill candidate 已写入输出目录: %s", draft_path)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[Planner] Draft Skill 生成失败（不影响主流程）: %s", exc)

    def _build_plan_id(self) -> str:
        raw = json.dumps(
            {"site_url": self.site_url, "user_request": self.user_request},
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def _load_saved_plan(self) -> TaskPlan | None:
        plan_file = Path(self.output_dir) / "task_plan.json"
        data = load_json_if_exists(plan_file)
        if not isinstance(data, dict):
            return None
        if str(data.get("site_url") or "") != self.site_url:
            return None
        if str(data.get("original_request") or "") != self.user_request:
            return None
        try:
            return TaskPlan.model_validate(data)
        except Exception:
            return None

    def _render_nodes(self, plan: TaskPlan) -> list[str]:
        children_by_parent: dict[str, list[PlanNode]] = {}
        journal_by_node: dict[str, list[PlanJournalEntry]] = {}
        for node in plan.nodes:
            parent_id = str(node.parent_node_id or "")
            children_by_parent.setdefault(parent_id, []).append(node)
        for entry in plan.journal:
            journal_by_node.setdefault(entry.node_id, []).append(entry)

        lines: list[str] = []
        for node in children_by_parent.get("", []):
            self._append_node(lines, node, children_by_parent, journal_by_node)
        return lines

    def _append_node(
        self,
        lines: list[str],
        node: PlanNode,
        children_by_parent: dict[str, list[PlanNode]],
        journal_by_node: dict[str, list[PlanJournalEntry]],
    ) -> None:
        level = max(3, node.depth + 3)
        heading_level = "#" * level
        marks: list[str] = []
        if node.is_leaf:
            marks.append("✅")
        if node.executable and not node.is_leaf:
            marks.append("可执行")
        suffix = f" {' '.join(marks)}" if marks else ""
        child_count = len(children_by_parent.get(node.node_id, []))
        child_text = f"（{child_count} 个子节点）" if child_count > 0 else ""

        lines.append(f"{heading_level} {node.name}{suffix}{child_text}")
        lines.append(f"- 节点ID: {node.node_id}")
        if node.url:
            lines.append(f"- URL: {node.url}")
        lines.append(f"- 类型: {node.node_type.value}")
        if node.task_description:
            lines.append(f"- 任务: {node.task_description}")
        if node.context:
            lines.append(f"- 上下文: {json.dumps(node.context, ensure_ascii=False)}")
        if node.observations:
            lines.append(f"- 观察: {node.observations}")

        related = journal_by_node.get(node.node_id, [])
        if related:
            lines.append(f"{'#' * (level + 1)} Journal")
            for entry in related:
                action = str(entry.action or "").strip()
                reason = str(entry.reason or "").strip()
                evidence = str(entry.evidence or "").strip()
                prefix = f"- [{entry.phase}] {action}".strip()
                if reason:
                    prefix = f"{prefix}: {reason}"
                lines.append(prefix)
                if evidence:
                    lines.append(f"  依据: {evidence}")
                if entry.metadata:
                    lines.append(f"  元数据: {json.dumps(entry.metadata, ensure_ascii=False)}")
        lines.append("")

        for child in children_by_parent.get(node.node_id, []):
            self._append_node(lines, child, children_by_parent, journal_by_node)

    def _render_subtasks(self, plan: TaskPlan) -> list[str]:
        lines: list[str] = []
        for subtask in plan.subtasks:
            lines.append(f"### {subtask.name} ✅")
            lines.append(f"- URL: {subtask.list_url}")
            lines.append(f"- 类型: {PlanNodeType.LEAF.value}")
            lines.append(f"- 任务: {subtask.task_description}")
            if subtask.context:
                lines.append(f"- 上下文: {json.dumps(subtask.context, ensure_ascii=False)}")
            lines.append("")
        return lines
