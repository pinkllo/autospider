"""子任务隔离执行器。

每个 SubTaskWorker 为一个子任务提供独立的执行环境：
- 独立输出目录
- 复用现有 run_pipeline() 作为执行引擎
- 根据配置选择 memory/redis，并在 redis 下做子任务队列隔离
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from ..common.config import config
from ..common.logger import get_logger
from ..pipeline.types import ExecutionRequest, PipelineMode, SubtaskOutcomeType
from ..domain.fields import FieldDefinition
from ..domain.planning import SubTask, SubTaskMode, format_execution_brief
from ..pipeline.helpers import build_execution_context
from ..crawler.planner.runtime import RuntimeExpansionService
from .runtime_controls import resolve_concurrency_settings

logger = get_logger(__name__)


def _resolve_runtime_replan_max_children(raw_value: object | None) -> int:
    candidate = config.planner.runtime_subtasks_max_children if raw_value is None else raw_value
    try:
        resolved = int(candidate or 0)
    except (TypeError, ValueError):
        resolved = 0
    return max(0, resolved)


def _resolve_runtime_subtasks_use_main_model(raw_value: object | None) -> bool:
    if raw_value is None:
        return bool(config.planner.runtime_subtasks_use_main_model)
    if isinstance(raw_value, bool):
        return raw_value
    return str(raw_value).strip().lower() not in {"0", "false", "no", "off", ""}


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
        headless: bool | None = None,
        thread_id: str = "",
        guard_intervention_mode: str = "blocking",
        consumer_concurrency: int | None = None,
        field_explore_count: int | None = None,
        field_validate_count: int | None = None,
        selected_skills: list[dict[str, str]] | None = None,
        plan_knowledge: str = "",
        task_plan_snapshot: dict | None = None,
        plan_journal: list[dict] | None = None,
        pipeline_mode: PipelineMode | None = None,
        runtime_expansion_service_cls: type | None = None,
        runtime_subtask_max_children: int | None = None,
        runtime_subtasks_use_main_model: bool | None = None,
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
        self.pipeline_mode = pipeline_mode
        self.runtime_subtask_max_children = runtime_subtask_max_children
        self.runtime_subtasks_use_main_model = runtime_subtasks_use_main_model
        service_cls = runtime_expansion_service_cls or RuntimeExpansionService
        self.runtime_expansion_service = service_cls()

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

    def _resolved_concurrency(self):
        return resolve_concurrency_settings(
            {
                "serial_mode": False,
                "consumer_concurrency": self.consumer_concurrency or 1,
                "global_browser_budget": None,
            }
        )

    def _build_run_namespace(self) -> str:
        """构建稳定且按子任务隔离的运行命名空间。"""
        payload = {
            "thread_id": str(self.thread_id or ""),
            "subtask_id": str(self.subtask.id or ""),
            "page_state_signature": str(self.subtask.page_state_signature or ""),
            "variant_label": str(self.subtask.variant_label or ""),
            "anchor_url": str(self.subtask.anchor_url or ""),
            "list_url": str(self.subtask.list_url or ""),
            "task_description": str(self.subtask.task_description or ""),
            "execution_brief": self.subtask.execution_brief.model_dump(mode="python"),
            "output_dir": str(self.output_dir or ""),
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def _normalize_runtime_journal_entries(self, entries: tuple[dict[str, str], ...]) -> list[dict]:
        created_at = datetime.now().isoformat(timespec="seconds")
        normalized: list[dict] = []
        for index, entry in enumerate(entries, start=1):
            payload = dict(entry)
            payload["entry_id"] = str(
                payload.get("entry_id") or f"runtime_{self.subtask.id}_{index}_{datetime.now().strftime('%H%M%S%f')}"
            )
            payload["created_at"] = str(payload.get("created_at") or created_at)
            normalized.append(payload)
        return normalized

    async def _expand_runtime_subtask(self) -> dict:
        expanded = await self.runtime_expansion_service.expand(
            subtask=self.subtask,
            output_dir=self.output_dir,
            headless=self.headless,
            thread_id=self.thread_id,
            guard_intervention_mode=self.guard_intervention_mode,
            global_browser_budget=self._resolved_concurrency().global_browser_budget,
            max_children=_resolve_runtime_replan_max_children(self.runtime_subtask_max_children),
            use_main_model=_resolve_runtime_subtasks_use_main_model(self.runtime_subtasks_use_main_model),
        )
        journal_entries = self._normalize_runtime_journal_entries(expanded.journal_entries)
        return {
            "execution_state": expanded.execution_state,
            "expand_request": (
                {
                    "parent_subtask_id": expanded.expand_request.parent_subtask_id,
                    "spawned_subtasks": list(expanded.expand_request.spawned_subtasks),
                    "journal_entries": journal_entries,
                    "reason": expanded.expand_request.reason,
                }
                if expanded.expand_request is not None
                else None
            ),
            "journal_entries": journal_entries,
            "effective_subtask": expanded.effective_subtask.model_dump(mode="python"),
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
            runtime_result = await self._expand_runtime_subtask()
            journal_entries = list(runtime_result.get("journal_entries") or [])
            working_subtask = SubTask.model_validate(
                runtime_result.get("effective_subtask") or self.subtask.model_dump(mode="python")
            )
            if runtime_result.get("execution_state") == "expanded":
                logger.info(
                    "[Worker:%s] 运行时扩树完成，返回 ExpandRequest",
                    self.subtask.id,
                )
                return {
                    "execution_state": "expanded",
                    "outcome_type": SubtaskOutcomeType.EXPANDED.value,
                    "expand_request": runtime_result.get("expand_request"),
                    "journal_entries": journal_entries,
                    "effective_subtask": working_subtask.model_dump(mode="python"),
                    "items_file": "",
                    "total_urls": 0,
                    "success_count": 0,
                }

        concurrency = self._resolved_concurrency()
        request = ExecutionRequest(
            list_url=working_subtask.list_url,
            task_description=working_subtask.task_description,
            request=working_subtask.task_description,
            fields=[
                field.model_dump(mode="python")
                for field in self._prepare_fields()
            ],
            execution_brief=working_subtask.execution_brief.model_dump(mode="python"),
            output_dir=self.output_dir,
            headless=self.headless,
            field_explore_count=self.field_explore_count,
            field_validate_count=self.field_validate_count,
            consumer_concurrency=concurrency.consumer_concurrency,
            max_pages=working_subtask.max_pages,
            target_url_count=working_subtask.target_url_count,
            pipeline_mode=self.pipeline_mode,
            guard_intervention_mode=self.guard_intervention_mode,
            guard_thread_id=self.thread_id,
            selected_skills=list(self.selected_skills or []),
            plan_knowledge=self.plan_knowledge,
            task_plan_snapshot=self.task_plan_snapshot,
            plan_journal=list(self.plan_journal or []),
            initial_nav_steps=list(working_subtask.nav_steps or []),
            anchor_url=working_subtask.anchor_url,
            page_state_signature=working_subtask.page_state_signature,
            variant_label=working_subtask.variant_label,
            execution_id=self._build_run_namespace(),
            global_browser_budget=concurrency.global_browser_budget,
        )
        context = build_execution_context(request, fields=self._prepare_fields())
        logger.info(
            "[Worker:%s] pipeline_mode=%s, execution_id=%s",
            self.subtask.id,
            context.pipeline_mode.value,
            context.execution_id,
        )
        result = await run_pipeline(context)
        outcome_state = str(result.get("outcome_state") or "").strip().lower()
        if outcome_state == "no_data":
            result["outcome_type"] = SubtaskOutcomeType.NO_DATA.value
        elif result.get("error"):
            result["outcome_type"] = SubtaskOutcomeType.SYSTEM_FAILURE.value
        elif int(result.get("success_count", 0) or 0) <= 0:
            result["outcome_type"] = SubtaskOutcomeType.BUSINESS_FAILURE.value
        else:
            result["outcome_type"] = SubtaskOutcomeType.SUCCESS.value

        logger.info(
            "[Worker:%s] 执行完成: 采集 %d 条, 成功 %d 条",
            self.subtask.id,
            result.get("total_urls", 0),
            result.get("success_count", 0),
        )
        result["journal_entries"] = journal_entries
        result["effective_subtask"] = working_subtask.model_dump(mode="python")
        result["execution_brief_text"] = format_execution_brief(working_subtask.execution_brief)
        return result
