"""Push-mode subscription: wraps pull loop + worker pool."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from .protocol import ResultStatus, TaskResult, TaskTicket
from .scheduler import TaskScheduler


class Subscription:
    def __init__(
        self,
        *,
        scheduler: TaskScheduler,
        handler: Callable[[TaskTicket], Awaitable[TaskResult]],
        labels: dict[str, str] | None = None,
        concurrency: int = 1,
        poll_interval: float = 1.0,
    ) -> None:
        self._scheduler = scheduler
        self._handler = handler
        self._labels = labels
        self._concurrency = max(1, concurrency)
        self._poll_interval = poll_interval
        self._running = False
        self._tasks: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._tasks = [
            asyncio.create_task(self._worker_loop(worker_id))
            for worker_id in range(self._concurrency)
        ]

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def _worker_loop(self, worker_id: int) -> None:
        while self._running:
            pulled = await self._scheduler.pull(labels=self._labels, batch_size=1)
            if not pulled:
                await asyncio.sleep(self._poll_interval)
                continue
            ticket = pulled[0]
            await self._scheduler.ack_start(ticket.ticket_id, agent_id=f"sub-worker-{worker_id}")
            try:
                result = await self._handler(ticket)
            except Exception as exc:
                result = TaskResult(
                    result_id=f"error-{ticket.ticket_id}",
                    ticket_id=ticket.ticket_id,
                    status=ResultStatus.FAILED,
                    error=str(exc)[:500],
                )
            await self._scheduler.report_result(result)
