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

    该类负责按照 TaskPlan 中的子任务列表并行执行采集任务，主要功能包括：
    1. 并发控制：使用 asyncio.Semaphore 限制同时运行的子任务数量。
    2. 进度持久化：每当子任务状态变化时，将进度写入 JSON 文件，支持程序中断后恢复执行。
    3. 错误处理与重试：对失败的子任务进行自动重试，支持熔断机制。
    4. 结果汇总：执行完成后生成包含成功/失败统计、采集数量及错误详情的汇总报告。
    """

    def __init__(
        self,
        plan: TaskPlan,
        fields: list[dict],
        output_dir: str = "output",
        headless: bool = False,
        max_concurrent: int | None = None,
    ):
        """初始化调度器。

        Args:
            plan: 任务执行计划，包含子任务列表。
            fields: 需要采集的数据字段定义。
            output_dir: 结果输出目录，默认为 "output"。
            headless: 是否以无头模式运行浏览器，默认为 False。
            max_concurrent: 最大并发子任务数，不指定则从配置中读取。
        """
        self.plan = plan
        self.fields = fields
        self.output_dir = output_dir
        self.headless = headless

        # 确定最大并发数，优先级：参数指定 > 配置文件
        max_conc = max_concurrent or config.planner.max_concurrent_subtasks
        self.semaphore = asyncio.Semaphore(max_conc)
        # 定义进度文件路径，用于中断恢复
        self.progress_path = Path(output_dir) / config.planner.progress_file

        # 用于进度文件写入的异步锁，防止并发写入冲突
        self._lock = asyncio.Lock()
        self._started_at = datetime.now()

    async def run(self) -> dict:
        """开始执行所有计划中的子任务。

        执行流程：
        1. 加载历史进度，恢复已完成的任务状态。
        2. 筛选出待处理（PENDING）或已失败（FAILED）的任务，并按优先级排序。
        3. 并行启动子任务处理器。
        4. 等待所有任务结束并返回统计汇总。

        Returns:
            dict: 包含执行结果统计的字典。
        """
        # 尝试从磁盘加载进度
        self._load_progress()

        # 任务选择逻辑：
        # - 只运行 PENDING（待处理）或 FAILED（已失败但可能可重试）的任务
        # - 排序规则：优先级数字越小越先执行，优先级相同时按 ID 排序
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

        # 启动所有子任务协作协程
        tasks = [self._run_subtask(st) for st in pending]
        # 使用 scatter/gather 模式并发运行。return_exceptions=True 确保个别任务崩溃不影响整体运行
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
        """执行单个子任务的生命周期管理（受并发信号量控制）。

        Args:
            subtask: 待执行的子任务对象。
        """
        # 获取并发槽位
        async with self.semaphore:
            logger.info("[Dispatcher] 开始子任务: %s (%s)", subtask.name, subtask.id)

            # 更新任务状态并持久化
            subtask.status = SubTaskStatus.RUNNING
            subtask.error = None
            await self._save_progress()

            # 创建具体的执行 Worker
            worker = SubTaskWorker(
                subtask=subtask,
                fields=self.fields,
                output_dir=self.output_dir,
                headless=self.headless,
            )

            try:
                # 设定超时时间，防止单个任务卡死整个流水线
                timeout = config.planner.subtask_timeout_minutes * 60
                result = await asyncio.wait_for(worker.execute(), timeout=timeout)

                # 解析执行结果
                subtask.collected_count = int(result.get("total_urls", 0) or 0)
                subtask.result_file = result.get("items_file", "")
                pipeline_error = str(result.get("error") or "").strip()

                if pipeline_error:
                    # Pipeline 内部报告了错误
                    subtask.status = SubTaskStatus.FAILED
                    subtask.error = f"pipeline_error: {pipeline_error}"[:500]
                    logger.warning(
                        "[Dispatcher] ✗ 子任务失败: %s — %s",
                        subtask.name,
                        subtask.error,
                    )
                elif subtask.collected_count <= 0:
                    # 运行正常但没有任何数据输出，视为失败（可能有反爬或页面结构变化）
                    subtask.status = SubTaskStatus.FAILED
                    subtask.error = "no_data_collected"
                    logger.warning(
                        "[Dispatcher] ✗ 子任务失败: %s — 未采集到任何记录",
                        subtask.name,
                    )
                else:
                    # 执行成功
                    subtask.status = SubTaskStatus.COMPLETED
                    logger.info(
                        "[Dispatcher] ✓ 子任务完成: %s, 采集 %d 条",
                        subtask.name,
                        subtask.collected_count,
                    )

            except asyncio.TimeoutError:
                # 处理异步超时
                subtask.error = f"超时 ({config.planner.subtask_timeout_minutes}分钟)"
                self._handle_failure(subtask)
                logger.warning("[Dispatcher] ⏰ 子任务超时: %s", subtask.name)

            except Exception as e:
                # 捕获其他非预期异常
                subtask.error = str(e)[:500]
                self._handle_failure(subtask)
                logger.error("[Dispatcher] ✗ 子任务失败: %s — %s", subtask.name, e)

            # 无论成功还是失败，最终保存一次进度
            await self._save_progress()

    def _handle_failure(self, subtask: SubTask) -> None:
        """统一处理子任务失败时的重试决策。

        Args:
            subtask: 失败的子任务对象。
        """
        subtask.retry_count += 1
        # 检查是否超过最大重试次数
        if subtask.retry_count <= config.planner.max_subtask_retries:
            # 标记回待处理，之后会被 run() 中的调度循环再次发现
            subtask.status = SubTaskStatus.PENDING
            logger.info(
                "[Dispatcher] 子任务 %s 将重试 (%d/%d)",
                subtask.name,
                subtask.retry_count,
                config.planner.max_subtask_retries,
            )
        else:
            # 重试机会耗尽，正式标记为 FAILED
            subtask.status = SubTaskStatus.FAILED
            logger.warning(
                "[Dispatcher] 子任务 %s 重试次数用尽，标记为失败", subtask.name
            )

    def _load_progress(self) -> None:
        """从本地 JSON 文件加载之前的执行进度。

        用于实现“断点续爬”：如果文件存在，则将已完成的任务状态映射回内存中的 Plan 对象。
        """
        if not self.progress_path.exists():
            return

        try:
            with open(self.progress_path, "r", encoding="utf-8") as f:
                saved = json.load(f)

            # 将进度文件中的子任务转换为 ID -> Data 的字典，方便查找
            status_map: dict[str, dict] = {}
            for st_data in saved.get("subtasks", []):
                st_id = st_data.get("id")
                if st_id:
                    status_map[st_id] = st_data

            restored = 0
            # 遍历内存中的计划，根据磁盘文件更新其状态
            for subtask in self.plan.subtasks:
                if subtask.id in status_map:
                    saved_data = status_map[subtask.id]
                    saved_status = saved_data.get("status")

                    # 仅恢复已成功的状态，避免将当前的失败状态错误覆盖
                    if saved_status == SubTaskStatus.COMPLETED:
                        subtask.status = SubTaskStatus.COMPLETED
                        subtask.collected_count = saved_data.get("collected_count", 0)
                        subtask.result_file = saved_data.get("result_file")
                        restored += 1
                    elif saved_status == SubTaskStatus.FAILED:
                        # 失败的任务仅恢复重试计数，以便继续重试
                        subtask.retry_count = saved_data.get("retry_count", 0)

            if restored:
                logger.info("[Dispatcher] 从进度文件恢复了 %d 个已完成子任务", restored)

        except Exception as e:
            logger.warning("[Dispatcher] 加载进度文件失败: %s", e)

    async def _save_progress(self) -> None:
        """将当前的执行进度实时保存到磁盘。

        通过 asyncio.Lock 确保在多子任务并发完成时，文件的写入是串行的。
        """
        async with self._lock:
            try:
                progress = {
                    "plan_id": self.plan.plan_id,
                    "updated_at": datetime.now().isoformat(),
                    # 使用 Pydantic 的 model_dump 序列化所有子任务状态
                    "subtasks": [st.model_dump() for st in self.plan.subtasks],
                }

                # 确保目录存在
                self.progress_path.parent.mkdir(parents=True, exist_ok=True)
                # 使用 utf-8 编码保存
                with open(self.progress_path, "w", encoding="utf-8") as f:
                    json.dump(progress, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.warning("[Dispatcher] 保存进度失败: %s", e)

    def _build_summary(self) -> dict:
        """根据当前所有子任务的状态，构建最终的汇总报告。

        Returns:
            dict: 报告内容，包括计划 ID、总计/成功/失败数量、采集条目总数和失败详情。
        """
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
