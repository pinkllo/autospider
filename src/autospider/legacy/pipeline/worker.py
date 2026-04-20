"""子任务隔离执行器。

每个 SubTaskWorker 为一个子任务提供独立的执行环境：
- 独立输出目录
- 复用现有 run_pipeline() 作为执行引擎
- 统一走 Redis，并按子任务隔离队列命名空间
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from ..common.config import config
from ..common.logger import get_logger
from ..domain.fields import FieldDefinition
from ...contexts.planning.domain import SubTask, SubTaskMode, format_execution_brief
from ..graph.decision_context import build_decision_context
from ..pipeline.helpers import build_execution_context
from ..pipeline.subtask_runtime import restore_subtask, subtask_to_payload
from ..pipeline.types import ExecutionRequest, PipelineMode, PipelineRunResult, SubtaskOutcomeType
from ...contexts.planning.application.handlers import RuntimeExpansionService
from .runtime_controls import resolve_concurrency_settings

logger = get_logger(__name__)

_CATEGORY_FIELD_ALIASES = {
    "category",
    "categoryname",
    "projectcategory",
    "分类",
    "所属分类",
    "分类名称",
    "分类类别",
}
_CATEGORY_FIELD_MARKERS = (
    "所属分类",
    "分类名称",
    "分类类别",
    "categoryname",
    "projectcategory",
)


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


def _resolve_outcome_type(result: PipelineRunResult) -> str:
    if result.summary.outcome_state == "no_data":
        return SubtaskOutcomeType.NO_DATA.value
    if result.error:
        return SubtaskOutcomeType.SYSTEM_FAILURE.value
    if result.summary.success_count <= 0:
        return SubtaskOutcomeType.BUSINESS_FAILURE.value
    return SubtaskOutcomeType.SUCCESS.value


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
        decision_context: dict | None = None,
        world_snapshot: dict | None = None,
        control_snapshot: dict | None = None,
        failure_records: list[dict] | None = None,
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
        self.decision_context = dict(decision_context or {})
        self.world_snapshot = dict(world_snapshot or {})
        self.control_snapshot = dict(control_snapshot or {})
        self.failure_records = [dict(item) for item in list(failure_records or [])]
        service_cls = runtime_expansion_service_cls or RuntimeExpansionService
        self.runtime_expansion_service = service_cls()

    def _prepare_fields(self) -> list[FieldDefinition]:
        """将字段定义字典转换为 FieldDefinition 列表。"""
        fields: list[FieldDefinition] = []
        source = self.subtask.fields if self.subtask.fields else self.raw_fields

        for f in source:
            if not isinstance(f, dict):
                continue
            try:
                extraction_source = f.get("extraction_source")
                fixed_value = f.get("fixed_value")
                if self._is_context_like_field(f):
                    subtask_context_value = self._resolve_explicit_context_value(f)
                    if subtask_context_value:
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
        name = self._normalize_field_lookup_key(field.get("name"))
        desc = self._normalize_field_lookup_key(field.get("description"))
        if name in _CATEGORY_FIELD_ALIASES:
            return True
        return any(marker in desc for marker in _CATEGORY_FIELD_MARKERS)

    def _resolve_explicit_context_value(self, field: dict | None = None) -> str:
        fixed_field_value = self._resolve_fixed_field_value(field)
        if fixed_field_value:
            return fixed_field_value
        scope_value = self._resolve_scope_value()
        if scope_value:
            return scope_value
        return self._resolve_context_value()

    def _resolve_fixed_field_value(self, field: dict | None = None) -> str:
        fixed_fields = dict(getattr(self.subtask, "fixed_fields", {}) or {})
        if not fixed_fields:
            return ""
        for lookup in self._build_field_lookup_keys(field):
            for key, value in fixed_fields.items():
                if self._normalize_field_lookup_key(key) != lookup:
                    continue
                resolved = str(value or "").strip()
                if resolved:
                    return resolved
        for key in ("category_name", "category", "所属分类", "分类"):
            resolved = str(fixed_fields.get(key) or "").strip()
            if resolved:
                return resolved
        return ""

    def _build_field_lookup_keys(self, field: dict | None) -> list[str]:
        if not isinstance(field, dict):
            return []
        keys: list[str] = []
        for raw in (field.get("name"), field.get("description")):
            normalized = self._normalize_field_lookup_key(raw)
            if normalized:
                keys.append(normalized)
        return keys

    def _normalize_field_lookup_key(self, value: object | None) -> str:
        normalized = "".join(str(value or "").strip().lower().split())
        return normalized.replace("_", "")

    def _resolve_scope_value(self) -> str:
        scope = dict(getattr(self.subtask, "scope", {}) or {})
        label = str(scope.get("label") or scope.get("name") or "").strip()
        if label:
            return label
        path = scope.get("path")
        if isinstance(path, (list, tuple)):
            segments = [str(item or "").strip() for item in path if str(item or "").strip()]
            if segments:
                return " > ".join(segments)
        return ""

    def _resolve_context_value(self) -> str:
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

    def _resolve_decision_context(self, subtask: SubTask) -> dict:
        if self.world_snapshot and self.control_snapshot:
            return build_decision_context(
                {
                    "world": self._build_runtime_world_snapshot(),
                    "control": dict(self.control_snapshot),
                },
                page_id=str(subtask.plan_node_id or ""),
            )
        return dict(self.decision_context or {})

    def _build_runtime_world_snapshot(self) -> dict:
        world = dict(self.world_snapshot or {})
        runtime_failures = [dict(item) for item in list(self.failure_records or [])]
        world["failure_records"] = runtime_failures
        raw_world_model = world.get("world_model")
        if isinstance(raw_world_model, dict):
            world_model = dict(raw_world_model)
            world_model["failure_records"] = runtime_failures
            world["world_model"] = world_model
        return world

    def _normalize_runtime_journal_entries(self, entries: tuple[dict[str, str], ...]) -> list[dict]:
        created_at = datetime.now().isoformat(timespec="seconds")
        normalized: list[dict] = []
        for index, entry in enumerate(entries, start=1):
            payload = dict(entry)
            payload["entry_id"] = str(
                payload.get("entry_id")
                or f"runtime_{self.subtask.id}_{index}_{datetime.now().strftime('%H%M%S%f')}"
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
            use_main_model=_resolve_runtime_subtasks_use_main_model(
                self.runtime_subtasks_use_main_model
            ),
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
            "effective_subtask": expanded.effective_subtask,
        }

    async def execute(self) -> dict:
        """执行子任务，返回 run_pipeline 的汇总结果。"""
        # 延迟导入避免循环依赖
        from .runner import run_pipeline

        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        working_subtask = self.subtask
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
            working_subtask = restore_subtask(
                runtime_result.get("effective_subtask") or self.subtask
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
                    "effective_subtask": subtask_to_payload(working_subtask),
                    "_effective_subtask": working_subtask,
                    "items_file": "",
                    "total_urls": 0,
                    "success_count": 0,
                }

        concurrency = self._resolved_concurrency()
        world_snapshot = dict(self.world_snapshot or {})
        decision_context = self._resolve_decision_context(working_subtask)
        request = ExecutionRequest(
            list_url=working_subtask.list_url,
            task_description=working_subtask.task_description,
            request=working_subtask.task_description,
            fields=[field.model_dump(mode="python") for field in self._prepare_fields()],
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
            decision_context=decision_context,
            world_snapshot=world_snapshot,
            failure_records=[dict(item) for item in list(self.failure_records or [])],
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
        pipeline_result = await run_pipeline(context)
        result = pipeline_result.to_payload()
        result["outcome_type"] = _resolve_outcome_type(pipeline_result)
        pipeline_result = PipelineRunResult.from_raw(result)

        logger.info(
            "[Worker:%s] 执行完成: 采集 %d 条, 成功 %d 条",
            self.subtask.id,
            pipeline_result.summary.total_urls,
            pipeline_result.summary.success_count,
        )
        result["journal_entries"] = journal_entries
        pipeline_result = PipelineRunResult.from_raw(result)
        result["effective_subtask"] = subtask_to_payload(working_subtask)
        result["_effective_subtask"] = working_subtask
        result["_pipeline_result"] = pipeline_result
        result["execution_brief_text"] = format_execution_brief(working_subtask.execution_brief)
        return result
