"""多子任务并行调度器。

协调多个子任务的并行执行，提供：
- 信号量并发控制
- 进度持久化与中断恢复
- 失败重试与熔断
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

from ..common.config import config
from ..common.logger import get_logger
from ..common.types import SubTask, SubTaskStatus, TaskPlan
from .worker import SubTaskWorker

logger = get_logger(__name__)


class TaskDispatcher:
    """多子任务并行调度器。

    按照 TaskPlan 中的子任务列表并行执行，使用信号量控制并发数。
    每完成/失败一个子任务会写入进度文件，支持中断后恢复。
    """

    def __init__(
        self,
        plan: TaskPlan,
        fields: list[dict],
        output_dir: str = "output",
        headless: bool = False,
        max_concurrent: int | None = None,
    ):
        self.plan = plan
        self.fields = fields
        self.output_dir = output_dir
        self.headless = headless

        max_conc = max_concurrent or config.planner.max_concurrent_subtasks
        self.semaphore = asyncio.Semaphore(max_conc)
        self.progress_path = Path(output_dir) / config.planner.progress_file

        self._lock = asyncio.Lock()
        self._started_at = datetime.now()

    async def run(self) -> dict:
        """执行所有子任务并返回汇总结果。"""
        self._load_progress()

        # 按优先级排序，过滤出需要执行的子任务
        pending = sorted(
            [
                st
                for st in self.plan.subtasks
                if st.status in (SubTaskStatus.PENDING, SubTaskStatus.FAILED)
            ],
            key=lambda st: (st.priority, st.id),
        )

        if not pending:
            logger.info("[Dispatcher] 没有需要执行的子任务")
            return self._build_summary()

        logger.info(
            "[Dispatcher] 共 %d 个子任务待执行（并发上限 %d）",
            len(pending),
            self.semaphore._value,
        )

        tasks = [self._run_subtask(st) for st in pending]
        await asyncio.gather(*tasks, return_exceptions=True)

        summary = self._build_summary()
        logger.info(
            "[Dispatcher] 全部完成: 成功 %d / 失败 %d / 总计 %d",
            summary["completed"],
            summary["failed"],
            summary["total"],
        )
        return summary

    async def _run_subtask(self, subtask: SubTask) -> None:
        """执行单个子任务（受信号量限制）。"""
        async with self.semaphore:
            logger.info("[Dispatcher] 开始子任务: %s (%s)", subtask.name, subtask.id)

            subtask.status = SubTaskStatus.RUNNING
            subtask.error = None
            await self._save_progress()

            worker = SubTaskWorker(
                subtask=subtask,
                fields=self.fields,
                output_dir=self.output_dir,
                headless=self.headless,
            )

            try:
                timeout = config.planner.subtask_timeout_minutes * 60
                result = await asyncio.wait_for(worker.execute(), timeout=timeout)

                subtask.collected_count = int(result.get("total_urls", 0) or 0)
                subtask.result_file = result.get("items_file", "")
                pipeline_error = str(result.get("error") or "").strip()

                if pipeline_error:
                    subtask.status = SubTaskStatus.FAILED
                    subtask.error = f"pipeline_error: {pipeline_error}"[:500]
                    logger.warning(
                        "[Dispatcher] ✗ 子任务失败: %s — %s",
                        subtask.name,
                        subtask.error,
                    )
                elif subtask.collected_count <= 0:
                    subtask.status = SubTaskStatus.FAILED
                    subtask.error = "no_data_collected"
                    logger.warning(
                        "[Dispatcher] ✗ 子任务失败: %s — 未采集到任何记录",
                        subtask.name,
                    )
                else:
                    subtask.status = SubTaskStatus.COMPLETED
                    logger.info(
                        "[Dispatcher] ✓ 子任务完成: %s, 采集 %d 条",
                        subtask.name,
                        subtask.collected_count,
                    )

            except asyncio.TimeoutError:
                subtask.error = f"超时 ({config.planner.subtask_timeout_minutes}分钟)"
                self._handle_failure(subtask)
                logger.warning("[Dispatcher] ⏰ 子任务超时: %s", subtask.name)

            except Exception as e:
                subtask.error = str(e)[:500]
                self._handle_failure(subtask)
                logger.error("[Dispatcher] ✗ 子任务失败: %s — %s", subtask.name, e)

            await self._save_progress()

    def _handle_failure(self, subtask: SubTask) -> None:
        """处理子任务失败：判断是否可以重试。"""
        subtask.retry_count += 1
        if subtask.retry_count <= config.planner.max_subtask_retries:
            subtask.status = SubTaskStatus.PENDING
            logger.info(
                "[Dispatcher] 子任务 %s 将重试 (%d/%d)",
                subtask.name,
                subtask.retry_count,
                config.planner.max_subtask_retries,
            )
        else:
            subtask.status = SubTaskStatus.FAILED
            logger.warning(
                "[Dispatcher] 子任务 %s 重试次数用尽，标记为失败", subtask.name
            )

    def _load_progress(self) -> None:
        """从进度文件恢复子任务状态（支持中断恢复）。"""
        if not self.progress_path.exists():
            return

        try:
            with open(self.progress_path, "r", encoding="utf-8") as f:
                saved = json.load(f)

            status_map: dict[str, dict] = {}
            for st_data in saved.get("subtasks", []):
                st_id = st_data.get("id")
                if st_id:
                    status_map[st_id] = st_data

            restored = 0
            for subtask in self.plan.subtasks:
                if subtask.id in status_map:
                    saved_data = status_map[subtask.id]
                    saved_status = saved_data.get("status")
                    if saved_status == SubTaskStatus.COMPLETED:
                        subtask.status = SubTaskStatus.COMPLETED
                        subtask.collected_count = saved_data.get("collected_count", 0)
                        subtask.result_file = saved_data.get("result_file")
                        restored += 1
                    elif saved_status == SubTaskStatus.FAILED:
                        subtask.retry_count = saved_data.get("retry_count", 0)

            if restored:
                logger.info("[Dispatcher] 从进度文件恢复了 %d 个已完成子任务", restored)

        except Exception as e:
            logger.warning("[Dispatcher] 加载进度文件失败: %s", e)

    async def _save_progress(self) -> None:
        """持久化当前进度到 JSON 文件。"""
        async with self._lock:
            try:
                progress = {
                    "plan_id": self.plan.plan_id,
                    "updated_at": datetime.now().isoformat(),
                    "subtasks": [st.model_dump() for st in self.plan.subtasks],
                }

                self.progress_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.progress_path, "w", encoding="utf-8") as f:
                    json.dump(progress, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.warning("[Dispatcher] 保存进度失败: %s", e)

    def _build_summary(self) -> dict:
        """构建汇总信息。"""
        completed = [st for st in self.plan.subtasks if st.status == SubTaskStatus.COMPLETED]
        failed = [st for st in self.plan.subtasks if st.status == SubTaskStatus.FAILED]

        return {
            "plan_id": self.plan.plan_id,
            "total": len(self.plan.subtasks),
            "completed": len(completed),
            "failed": len(failed),
            "pending": len(self.plan.subtasks) - len(completed) - len(failed),
            "total_collected": sum(st.collected_count for st in completed),
            "started_at": self._started_at.isoformat(),
            "finished_at": datetime.now().isoformat(),
            "failed_details": [
                {"id": st.id, "name": st.name, "error": st.error} for st in failed
            ],
        }
