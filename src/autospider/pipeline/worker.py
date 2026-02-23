"""子任务隔离执行器。

每个 SubTaskWorker 为一个子任务提供独立的执行环境：
- 独立输出目录
- 复用现有 run_pipeline() 作为执行引擎
- 强制 memory 模式（避免子任务间资源冲突）
"""

from __future__ import annotations

from pathlib import Path

from ..common.config import config
from ..common.logger import get_logger
from ..common.types import SubTask
from ..field import FieldDefinition

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
    ):
        self.subtask = subtask
        self.raw_fields = fields
        self.output_dir = str(Path(output_dir) / f"subtask_{subtask.id}")
        self.headless = headless

    def _prepare_fields(self) -> list[FieldDefinition]:
        """将字段定义字典转换为 FieldDefinition 列表。"""
        fields: list[FieldDefinition] = []
        source = self.subtask.fields if self.subtask.fields else self.raw_fields

        for f in source:
            if not isinstance(f, dict):
                continue
            try:
                fields.append(
                    FieldDefinition(
                        name=f.get("name", ""),
                        description=f.get("description", ""),
                        required=f.get("required", True),
                        data_type=f.get("data_type", "text"),
                        example=f.get("example"),
                    )
                )
            except Exception:
                continue

        return fields

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

        result = await run_pipeline(
            list_url=self.subtask.list_url,
            task_description=self.subtask.task_description,
            fields=self._prepare_fields(),
            output_dir=self.output_dir,
            headless=self.headless,
            max_pages=self.subtask.max_pages,
            target_url_count=self.subtask.target_url_count,
            consumer_concurrency=config.planner.subtask_consumer_concurrency,
            pipeline_mode="memory",  # 子任务级别统一使用内存队列
        )

        logger.info(
            "[Worker:%s] 执行完成: 采集 %d 条, 成功 %d 条",
            self.subtask.id,
            result.get("total_urls", 0),
            result.get("success_count", 0),
        )

        return result
