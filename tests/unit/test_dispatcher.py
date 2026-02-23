"""TaskDispatcher 单元测试。"""

from __future__ import annotations

import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

from autospider.common.types import SubTask, SubTaskStatus, TaskPlan
from autospider.pipeline.dispatcher import TaskDispatcher


def _make_plan(subtasks: list[SubTask]) -> TaskPlan:
    return TaskPlan(
        plan_id="test_plan",
        original_request="测试需求",
        site_url="https://example.com",
        subtasks=subtasks,
        total_subtasks=len(subtasks),
    )


def _make_subtask(id: str, name: str = "", **kwargs) -> SubTask:
    return SubTask(
        id=id,
        name=name or f"子任务_{id}",
        list_url=f"https://example.com/{id}",
        task_description=f"采集 {name or id} 数据",
        **kwargs,
    )


class TestDispatcherBasic:
    """基础功能测试。"""

    @pytest.mark.asyncio
    async def test_empty_plan(self, tmp_path):
        """空计划应直接返回汇总。"""
        plan = _make_plan([])
        dispatcher = TaskDispatcher(plan=plan, fields=[], output_dir=str(tmp_path))
        result = await dispatcher.run()
        assert result["total"] == 0
        assert result["completed"] == 0

    @pytest.mark.asyncio
    async def test_all_completed_skip(self, tmp_path):
        """已完成的子任务应被跳过。"""
        st = _make_subtask("01", status=SubTaskStatus.COMPLETED, collected_count=10)
        plan = _make_plan([st])
        dispatcher = TaskDispatcher(plan=plan, fields=[], output_dir=str(tmp_path))
        result = await dispatcher.run()
        assert result["completed"] == 1
        assert result["pending"] == 0


class TestDispatcherExecution:
    """执行逻辑测试。"""

    @pytest.mark.asyncio
    async def test_successful_subtask(self, tmp_path):
        """子任务执行成功的场景。"""
        st = _make_subtask("01")
        plan = _make_plan([st])

        mock_result = {"total_urls": 5, "success_count": 5, "items_file": "out.jsonl"}

        with patch(
            "autospider.pipeline.dispatcher.SubTaskWorker"
        ) as MockWorker:
            mock_instance = MagicMock()
            mock_instance.execute = AsyncMock(return_value=mock_result)
            MockWorker.return_value = mock_instance

            dispatcher = TaskDispatcher(
                plan=plan, fields=[], output_dir=str(tmp_path)
            )
            result = await dispatcher.run()

        assert result["completed"] == 1
        assert result["failed"] == 0
        assert st.status == SubTaskStatus.COMPLETED
        assert st.collected_count == 5

    @pytest.mark.asyncio
    async def test_failed_subtask_retry(self, tmp_path):
        """失败的子任务应自动重试。"""
        st = _make_subtask("01")
        plan = _make_plan([st])

        call_count = 0

        async def mock_execute():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise RuntimeError("模拟错误")
            return {"total_urls": 3, "success_count": 3, "items_file": "out.jsonl"}

        with patch(
            "autospider.pipeline.dispatcher.SubTaskWorker"
        ) as MockWorker:
            mock_instance = MagicMock()
            mock_instance.execute = mock_execute
            MockWorker.return_value = mock_instance

            dispatcher = TaskDispatcher(
                plan=plan, fields=[], output_dir=str(tmp_path)
            )
            # Dispatcher 会在单次 run 中只调度一轮；
            # 重试需要重新运行
            result = await dispatcher.run()

            # 第一次应该失败并被标记为 PENDING（可重试）
            if st.status == SubTaskStatus.PENDING:
                result = await dispatcher.run()

        # 最终应该要么成功要么用尽重试
        assert st.retry_count >= 1


class TestDispatcherProgress:
    """进度持久化测试。"""

    @pytest.mark.asyncio
    async def test_progress_saved(self, tmp_path):
        """执行后应保存进度文件。"""
        st = _make_subtask("01")
        plan = _make_plan([st])

        with patch(
            "autospider.pipeline.dispatcher.SubTaskWorker"
        ) as MockWorker:
            mock_instance = MagicMock()
            mock_instance.execute = AsyncMock(
                return_value={"total_urls": 1, "success_count": 1}
            )
            MockWorker.return_value = mock_instance

            dispatcher = TaskDispatcher(
                plan=plan, fields=[], output_dir=str(tmp_path)
            )
            await dispatcher.run()

        progress_file = tmp_path / "task_progress.json"
        assert progress_file.exists()

        progress = json.loads(progress_file.read_text(encoding="utf-8"))
        assert progress["plan_id"] == "test_plan"
        assert len(progress["subtasks"]) == 1
        assert progress["subtasks"][0]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_progress_restore(self, tmp_path):
        """应能从进度文件恢复已完成的子任务。"""
        # 先保存一个已完成的进度
        progress_data = {
            "plan_id": "test_plan",
            "subtasks": [
                {
                    "id": "01",
                    "status": "completed",
                    "collected_count": 10,
                    "result_file": "out.jsonl",
                }
            ],
        }
        progress_file = tmp_path / "task_progress.json"
        progress_file.write_text(json.dumps(progress_data), encoding="utf-8")

        st = _make_subtask("01")
        plan = _make_plan([st])

        dispatcher = TaskDispatcher(
            plan=plan, fields=[], output_dir=str(tmp_path)
        )

        # load_progress 会在 run() 中被调用
        result = await dispatcher.run()

        # 已完成的子任务应被跳过
        assert result["completed"] == 1
        assert result["pending"] == 0


class TestConcurrencyControl:
    """并发控制测试。"""

    @pytest.mark.asyncio
    async def test_semaphore_limits(self, tmp_path):
        """信号量应限制同时运行的子任务数。"""
        max_concurrent_observed = 0
        current_concurrent = 0
        lock = asyncio.Lock()

        async def mock_execute():
            nonlocal max_concurrent_observed, current_concurrent
            async with lock:
                current_concurrent += 1
                max_concurrent_observed = max(max_concurrent_observed, current_concurrent)
            await asyncio.sleep(0.1)
            async with lock:
                current_concurrent -= 1
            return {"total_urls": 1, "success_count": 1}

        subtasks = [_make_subtask(f"{i:02d}") for i in range(5)]
        plan = _make_plan(subtasks)

        with patch(
            "autospider.pipeline.dispatcher.SubTaskWorker"
        ) as MockWorker:
            mock_instance = MagicMock()
            mock_instance.execute = mock_execute
            MockWorker.return_value = mock_instance

            dispatcher = TaskDispatcher(
                plan=plan,
                fields=[],
                output_dir=str(tmp_path),
                max_concurrent=2,
            )
            await dispatcher.run()

        assert max_concurrent_observed <= 2
