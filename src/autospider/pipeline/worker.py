"""子任务隔离执行器。

每个 SubTaskWorker 为一个子任务提供独立的执行环境：
- 独立输出目录
- 复用现有 run_pipeline() 作为执行引擎
- 根据配置选择 memory/redis，并在 redis 下做子任务队列隔离
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

from ..common.browser import BrowserSession
from ..common.config import config
from ..common.logger import get_logger
from ..domain.fields import FieldDefinition
from ..domain.planning import SubTask, SubTaskMode, format_execution_brief
from ..crawler.planner import TaskPlanner

logger = get_logger(__name__)


def _resolve_runtime_replan_max_children() -> int:
    raw_value = getattr(config.planner, "runtime_subtasks_max_children", 0)
    try:
        resolved = int(raw_value or 0)
    except (TypeError, ValueError):
        resolved = 0
    return max(0, resolved)


class SubTaskWorker:
    """隔离的子任务执行器。

    每个 Worker 将子任务路由到独立的输出子目录，
    并复用现有的 run_pipeline() 进行完整的 Producer-Explorer-Consumer 流程。
    """

    def __init__(
        self,
        subtask: SubTask,
        fields: list[dict],
        output_dir: str = "output",
        headless: bool = False,
        thread_id: str = "",
        guard_intervention_mode: str = "blocking",
        consumer_concurrency: int | None = None,
        field_explore_count: int | None = None,
        field_validate_count: int | None = None,
        selected_skills: list[dict[str, str]] | None = None,
        plan_knowledge: str = "",
        task_plan_snapshot: dict | None = None,
        plan_journal: list[dict] | None = None,
    ):
        self.subtask = subtask
        self.raw_fields = fields
        self.output_dir = str(Path(output_dir) / f"subtask_{subtask.id}")
        self.headless = headless
        self.thread_id = thread_id
        self.guard_intervention_mode = guard_intervention_mode
        self.consumer_concurrency = consumer_concurrency
        self.field_explore_count = field_explore_count
        self.field_validate_count = field_validate_count
        self.selected_skills = list(selected_skills or [])
        self.plan_knowledge = str(plan_knowledge or "")
        self.task_plan_snapshot = dict(task_plan_snapshot or {})
        self.plan_journal = list(plan_journal or [])

    def _prepare_fields(self) -> list[FieldDefinition]:
        """将字段定义字典转换为 FieldDefinition 列表。"""
        fields: list[FieldDefinition] = []
        source = self.subtask.fields if self.subtask.fields else self.raw_fields
        subtask_context_value = self._resolve_explicit_context_value()

        for f in source:
            if not isinstance(f, dict):
                continue
            try:
                extraction_source = f.get("extraction_source")
                fixed_value = f.get("fixed_value")
                if (
                    not extraction_source
                    and not fixed_value
                    and subtask_context_value
                    and self._is_context_like_field(f)
                ):
                    extraction_source = "subtask_context"
                    fixed_value = subtask_context_value

                fields.append(
                    FieldDefinition(
                        name=f.get("name", ""),
                        description=f.get("description", ""),
                        required=f.get("required", True),
                        data_type=f.get("data_type", "text"),
                        example=f.get("example"),
                        extraction_source=extraction_source,
                        fixed_value=fixed_value,
                    )
                )
            except Exception:
                continue

        return fields

    def _is_context_like_field(self, field: dict) -> bool:
        name = str(field.get("name") or "").strip().lower()
        desc = str(field.get("description") or "").strip().lower()
        text = f"{name} {desc}"
        keywords = (
            "category",
            "分类",
            "类别",
            "类型",
            "tag",
            "标签",
            "所属",
            "行业",
            "project_category",
        )
        return any(k in text for k in keywords)

    def _resolve_explicit_context_value(self) -> str:
        context = dict(getattr(self.subtask, "context", {}) or {})
        for key in ("category_name", "category", "所属分类", "分类"):
            value = str(context.get(key) or "").strip()
            if value:
                return value
        return ""

    def _resolve_pipeline_transport(self) -> tuple[str, str | None]:
        """解析子任务的通道模式与 redis key 前缀。"""
        if config.redis.enabled:
            base_prefix = (config.redis.key_prefix or "autospider:urls").strip()
            run_namespace = self._build_run_namespace()
            redis_key_prefix = f"{base_prefix}:run:{run_namespace}:subtask:{self.subtask.id}"
            return "redis", redis_key_prefix
        return "memory", None

    def _build_run_namespace(self) -> str:
        """构建稳定的运行命名空间，避免不同运行间 Redis 队列串台。"""
        if self.thread_id:
            return self.thread_id
        payload = {
            "page_state_signature": str(self.subtask.page_state_signature or ""),
            "anchor_url": str(self.subtask.anchor_url or ""),
            "list_url": str(self.subtask.list_url or ""),
            "task_description": str(self.subtask.task_description or ""),
            "output_dir": str(self.output_dir or ""),
        }
        raw = "|".join(f"{key}={value}" for key, value in payload.items())
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def _build_runtime_journal_entry(
        self,
        *,
        action: str,
        reason: str,
        evidence: str = "",
        metadata: dict[str, str] | None = None,
    ) -> dict:
        return {
            "entry_id": f"runtime_{self.subtask.id}_{action}_{datetime.now().strftime('%H%M%S%f')}",
            "node_id": str(self.subtask.plan_node_id or ""),
            "phase": "pipeline",
            "action": action,
            "reason": reason,
            "evidence": evidence,
            "metadata": dict(metadata or {}),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }

    async def _plan_runtime_children(self) -> dict:
        session = BrowserSession(
            headless=self.headless,
            guard_intervention_mode=self.guard_intervention_mode,
            guard_thread_id=self.thread_id,
        )
        await session.start()
        try:
            planner = TaskPlanner(
                page=session.page,
                site_url=str(self.subtask.anchor_url or self.subtask.list_url or ""),
                user_request=str(self.subtask.task_description or ""),
                output_dir=self.output_dir,
                use_main_model=bool(getattr(config.planner, "runtime_subtasks_use_main_model", False)),
            )
            result = await planner.plan_runtime_subtasks(
                parent_subtask=self.subtask,
                max_children=_resolve_runtime_replan_max_children(),
            )
        finally:
            await session.stop()

        journal_entries: list[dict] = []
        if result.children:
            journal_entries.append(
                self._build_runtime_journal_entry(
                    action="runtime_expand",
                    reason=f"识别到 {len(result.children)} 个下级相关分类，当前任务转为 expanded",
                    evidence="; ".join(child.name for child in result.children),
                    metadata={"child_count": str(len(result.children))},
                )
            )
            journal_entries.append(
                self._build_runtime_journal_entry(
                    action="runtime_spawn_children",
                    reason="生成运行时子任务",
                    evidence="; ".join(child.task_description for child in result.children),
                    metadata={"spawned_ids": ",".join(child.id for child in result.children)},
                )
            )
            return {
                "execution_state": "expanded",
                "spawned_subtasks": [child.model_dump(mode="python") for child in result.children],
                "journal_entries": journal_entries,
                "effective_subtask": self.subtask.model_dump(mode="python"),
            }

        collect_subtask = self.subtask.model_copy(
            update={
                "mode": SubTaskMode.COLLECT,
                "task_description": result.collect_task_description,
                "execution_brief": result.collect_execution_brief,
            }
        )
        journal_entries.append(
            self._build_runtime_journal_entry(
                action="runtime_leaf_confirmed",
                reason="当前任务未识别到更深相关分类，确认为叶子采集任务",
                evidence=str(result.analysis.get("observations") or ""),
            )
        )
        journal_entries.append(
            self._build_runtime_journal_entry(
                action="runtime_expand_to_collect",
                reason="expand 任务就地转为 collect 执行",
                evidence=result.collect_task_description,
                metadata={"mode": SubTaskMode.COLLECT.value},
            )
        )
        return {
            "execution_state": "collect",
            "spawned_subtasks": [],
            "journal_entries": journal_entries,
            "effective_subtask": collect_subtask.model_dump(mode="python"),
        }

    async def execute(self) -> dict:
        """执行子任务，返回 run_pipeline 的汇总结果。"""
        # 延迟导入避免循环依赖
        from .runner import run_pipeline

        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        working_subtask = self.subtask
        spawned_subtasks: list[dict] = []
        journal_entries: list[dict] = []

        logger.info(
            "[Worker:%s] 开始执行: %s -> %s",
            self.subtask.id,
            self.subtask.name,
            self.subtask.list_url[:80],
        )
        if self.subtask.mode == SubTaskMode.EXPAND:
            runtime_result = await self._plan_runtime_children()
            spawned_subtasks = list(runtime_result.get("spawned_subtasks") or [])
            journal_entries = list(runtime_result.get("journal_entries") or [])
            working_subtask = SubTask.model_validate(
                runtime_result.get("effective_subtask") or self.subtask.model_dump(mode="python")
            )
            if runtime_result.get("execution_state") == "expanded":
                logger.info(
                    "[Worker:%s] 运行时扩树完成，新增 %d 个子任务",
                    self.subtask.id,
                    len(spawned_subtasks),
                )
                return {
                    "execution_state": "expanded",
                    "spawned_subtasks": spawned_subtasks,
                    "journal_entries": journal_entries,
                    "effective_subtask": working_subtask.model_dump(mode="python"),
                    "items_file": "",
                    "total_urls": 0,
                    "success_count": 0,
                }

        pipeline_mode, redis_key_prefix = self._resolve_pipeline_transport()
        logger.info(
            "[Worker:%s] pipeline_mode=%s, redis_key_prefix=%s",
            self.subtask.id,
            pipeline_mode,
            redis_key_prefix or "(N/A)",
        )

        result = await run_pipeline(
            list_url=working_subtask.list_url,
            task_description=working_subtask.task_description,
            fields=self._prepare_fields(),
            output_dir=self.output_dir,
            headless=self.headless,
            max_pages=working_subtask.max_pages,
            target_url_count=working_subtask.target_url_count,
            consumer_concurrency=(
                self.consumer_concurrency
                if self.consumer_concurrency is not None
                else config.planner.subtask_consumer_concurrency
            ),
            explore_count=self.field_explore_count,
            validate_count=self.field_validate_count,
            pipeline_mode=pipeline_mode,
            redis_key_prefix=redis_key_prefix,
            guard_intervention_mode=self.guard_intervention_mode,
            guard_thread_id=self.thread_id,
            selected_skills=self.selected_skills,
            plan_knowledge=self.plan_knowledge,
            task_plan_snapshot=self.task_plan_snapshot,
            plan_journal=self.plan_journal,
            initial_nav_steps=list(working_subtask.nav_steps or []),
            anchor_url=working_subtask.anchor_url,
            page_state_signature=working_subtask.page_state_signature,
            variant_label=working_subtask.variant_label,
            execution_brief=working_subtask.execution_brief.model_dump(mode="python"),
        )

        logger.info(
            "[Worker:%s] 执行完成: 采集 %d 条, 成功 %d 条",
            self.subtask.id,
            result.get("total_urls", 0),
            result.get("success_count", 0),
        )
        result["spawned_subtasks"] = spawned_subtasks
        result["journal_entries"] = journal_entries
        result["effective_subtask"] = working_subtask.model_dump(mode="python")
        result["execution_brief_text"] = format_execution_brief(working_subtask.execution_brief)
        return result
