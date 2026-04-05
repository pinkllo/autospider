"""子任务隔离执行器。

每个 SubTaskWorker 为一个子任务提供独立的执行环境：
- 独立输出目录
- 复用现有 run_pipeline() 作为执行引擎
- 根据配置选择 memory/redis，并在 redis 下做子任务队列隔离
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..common.config import config
from ..common.logger import get_logger
from ..domain.fields import FieldDefinition
from ..domain.planning import SubTask

logger = get_logger(__name__)


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

    def _prepare_fields(self) -> list[FieldDefinition]:
        """将字段定义字典转换为 FieldDefinition 列表。"""
        fields: list[FieldDefinition] = []
        source = self.subtask.fields if self.subtask.fields else self.raw_fields
        subtask_context_value = self._infer_subtask_context_value()

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

    def _infer_subtask_context_value(self) -> str:
        # 优先从 task_description 里提取被引号包裹的分类词，取最后一个更接近具体子类
        task_desc = str(self.subtask.task_description or "")
        quoted = re.findall(r"[\"“'‘](.*?)[\"”'’]", task_desc)
        if quoted:
            candidate = str(quoted[-1]).strip()
            if candidate:
                return candidate

        # 回退使用子任务名，并去掉常见后缀噪声
        name = str(self.subtask.name or "").strip()
        name = re.sub(r"(子任务|分类|类别|列表|采集|抓取|任务)$", "", name).strip(":-： ")
        return name

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
            "list_url": str(self.subtask.list_url or ""),
            "task_description": str(self.subtask.task_description or ""),
            "output_dir": str(self.output_dir or ""),
        }
        raw = "|".join(f"{key}={value}" for key, value in payload.items())
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    async def execute(self) -> dict:
        """执行子任务，返回 run_pipeline 的汇总结果。"""
        # 延迟导入避免循环依赖
        from .runner import run_pipeline

        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

        logger.info(
            "[Worker:%s] 开始执行: %s -> %s",
            self.subtask.id,
            self.subtask.name,
            self.subtask.list_url[:80],
        )
        pipeline_mode, redis_key_prefix = self._resolve_pipeline_transport()
        logger.info(
            "[Worker:%s] pipeline_mode=%s, redis_key_prefix=%s",
            self.subtask.id,
            pipeline_mode,
            redis_key_prefix or "(N/A)",
        )

        result = await run_pipeline(
            list_url=self.subtask.list_url,
            task_description=self.subtask.task_description,
            fields=self._prepare_fields(),
            output_dir=self.output_dir,
            headless=self.headless,
            max_pages=self.subtask.max_pages,
            target_url_count=self.subtask.target_url_count,
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
        )

        logger.info(
            "[Worker:%s] 执行完成: 采集 %d 条, 成功 %d 条",
            self.subtask.id,
            result.get("total_urls", 0),
            result.get("success_count", 0),
        )

        return result
