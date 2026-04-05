"""Planner persistence and knowledge artifact helpers."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import yaml

from ...common.logger import get_logger
from ...common.storage.idempotent_io import load_json_if_exists, write_json_idempotent
from ...domain.planning import SubTask, TaskPlan

logger = get_logger(__name__)


class PlannerArtifacts:
    """Builds and persists planner outputs without owning traversal logic."""

    def __init__(self, *, site_url: str, user_request: str, output_dir: str) -> None:
        self.site_url = site_url
        self.user_request = user_request
        self.output_dir = output_dir

    def build_plan(self, subtasks: list[SubTask]) -> TaskPlan:
        existing = self._load_saved_plan()
        created_at = existing.created_at if existing else ""
        updated_at = existing.updated_at if existing else ""

        return TaskPlan(
            plan_id=(existing.plan_id if existing else self._build_plan_id()),
            original_request=self.user_request,
            site_url=self.site_url,
            subtasks=subtasks,
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

    def write_knowledge_doc(self, knowledge_entries: list[dict], plan: TaskPlan) -> None:
        content = self.build_knowledge_doc(knowledge_entries, plan)
        if not content:
            return

        doc_path = Path(self.output_dir) / "plan_knowledge.md"
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text(content, encoding="utf-8")
        logger.info("[Planner] 知识文档已写入: %s", doc_path)

    def build_knowledge_doc(self, knowledge_entries: list[dict], plan: TaskPlan) -> str:
        if not knowledge_entries:
            return ""

        domain = urlparse(self.site_url).netloc
        leaf_count = sum(1 for entry in knowledge_entries if entry["is_leaf"])

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

        for entry in knowledge_entries:
            depth = entry["depth"]
            heading_level = "#" * (depth + 3)
            leaf_mark = " ✅" if entry["is_leaf"] else ""
            children_info = ""
            if not entry["is_leaf"] and entry["children_count"] > 0:
                children_info = f"（{entry['children_count']} 个子分类）"

            lines.append(f"{heading_level} {entry['name']}{leaf_mark}{children_info}")
            lines.append(f"- URL: {entry['url']}")
            lines.append(f"- 类型: {entry['page_type']}")
            if entry["observations"]:
                lines.append(f"- 观察: {entry['observations']}")
            lines.append("")

        return "\n".join(lines)

    def sediment_draft_skill(self, knowledge_entries: list[dict], plan: TaskPlan) -> None:
        if not knowledge_entries:
            return

        try:
            from ...common.experience import SkillStore

            domain = urlparse(self.site_url).netloc
            subtask_names = [subtask.name for subtask in plan.subtasks]
            frontmatter = yaml.safe_dump(
                {
                    "name": f"{domain} 站点采集",
                    "description": (
                        f"{domain} 数据采集技能（草稿）。DFS 发现阶段生成，待 Worker 执行后补充字段提取规则。"
                    ),
                },
                allow_unicode=True,
                sort_keys=False,
            ).strip()

            lines: list[str] = []
            lines.append("---")
            lines.extend(frontmatter.splitlines())
            lines.append("---")
            lines.append("")
            lines.append(f"# {domain} 采集指南（草稿）")
            lines.append("")
            lines.append("## 基本信息")
            lines.append("")
            lines.append(f"- **列表页 URL**: `{self.site_url}`")
            lines.append(f"- **任务描述**: {self.user_request}")
            lines.append(f"- **状态**: 📝 draft")
            lines.append("")

            if subtask_names:
                lines.append("## 子任务")
                lines.append("")
                lines.append(f"本站共 {len(subtask_names)} 个子任务分类：")
                lines.append("")
                for subtask_name in subtask_names:
                    lines.append(f"- {subtask_name}")
                lines.append("")

            knowledge_path = Path(self.output_dir) / "plan_knowledge.md"
            if knowledge_path.exists():
                knowledge = knowledge_path.read_text(encoding="utf-8")
                lines.append("## DFS 发现过程")
                lines.append("")
                lines.append(knowledge.strip())
                lines.append("")

            content = "\n".join(lines)
            store = SkillStore(skills_dir=Path(self.output_dir) / "draft_skills")
            skill_path = store.save(domain, content)
            logger.info("[Planner] Draft Skill 已写入输出目录: %s", skill_path)
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
