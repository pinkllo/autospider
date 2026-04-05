"""Pipeline orchestration helpers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from ..common.browser.intervention import BrowserInterventionRequired
from ..common.channel.base import URLChannel
from ..common.config import config
from ..common.experience import SkillRuntime
from ..common.logger import get_logger
from ..domain.fields import FieldDefinition
from .progress_tracker import TaskProgressTracker

logger = get_logger(__name__)
@dataclass(slots=True)
class PipelineSessionBundle:
    list_session: Any
    detail_session: Any

    async def start(self) -> None:
        await self.list_session.start()
        await self.detail_session.start()

    async def stop(self) -> None:
        await self.list_session.stop()
        await self.detail_session.stop()


@dataclass(slots=True)
class PipelineRuntimeContext:
    list_url: str
    task_description: str
    fields: list[FieldDefinition]
    output_dir: str
    headless: bool
    explore_count: int
    validate_count: int
    consumer_workers: int
    max_pages: int | None
    target_url_count: int | None
    guard_intervention_mode: str
    guard_thread_id: str
    selected_skills: list[dict[str, str]] | None
    channel: URLChannel
    redis_manager: object | None
    run_records: dict[str, dict]
    summary: dict[str, Any]
    tracker: TaskProgressTracker
    skill_runtime: SkillRuntime
    sessions: PipelineSessionBundle
    plan_knowledge: str = ""
    url_only_mode: bool = False
    producer_done: asyncio.Event = field(default_factory=asyncio.Event)
    state: dict[str, object] = field(
        default_factory=lambda: {
            "collection_config": {},
            "extraction_config": {},
            "validation_failures": [],
            "error": None,
        }
    )


@dataclass(frozen=True, slots=True)
class PipelineRuntimeDependencies:
    browser_session_factory: Callable[..., Any]
    collector_cls: type
    detail_page_worker_cls: type
    set_state_error: Callable[[dict[str, object], str], None]
    process_task: Callable[..., Awaitable[None]]


class ProducerService:
    def __init__(self, context: PipelineRuntimeContext, deps: PipelineRuntimeDependencies) -> None:
        self.context = context
        self.deps = deps

    async def run(self) -> None:
        try:
            collector = self.deps.collector_cls(
                page=self.context.sessions.list_session.page,
                list_url=self.context.list_url,
                task_description=self.context.task_description,
                explore_count=self.context.explore_count,
                output_dir=self.context.output_dir,
                url_channel=self.context.channel,
                redis_manager=self.context.redis_manager,
                target_url_count=self.context.target_url_count,
                max_pages=self.context.max_pages,
                persist_progress=False,
                skill_runtime=self.context.skill_runtime,
                selected_skills=self.context.selected_skills,
            )
            result = await collector.run()
            self.context.summary["collected_urls"] = len(result.collected_urls)
            common_detail_xpath = getattr(collector, "common_detail_xpath", None)
            if common_detail_xpath is not None:
                common_detail_xpath = str(common_detail_xpath).strip() or None
            self.context.state["collection_config"] = {
                "nav_steps": list(getattr(collector, "nav_steps", []) or []),
                "common_detail_xpath": common_detail_xpath,
                "pagination_xpath": (
                    str(getattr(getattr(collector, "pagination_handler", None), "pagination_xpath", "") or "")
                    or None
                ),
                "jump_widget_xpath": dict(
                    getattr(getattr(collector, "pagination_handler", None), "jump_widget_xpath", None) or {}
                )
                or None,
                "list_url": self.context.list_url,
                "task_description": self.context.task_description,
            }
            await self.context.tracker.set_total(len(result.collected_urls))
        except BrowserInterventionRequired:
            raise
        except Exception as exc:  # noqa: BLE001
            self.deps.set_state_error(self.context.state, f"producer_error: {exc}")
            logger.info("[Pipeline] Producer failed: %s", exc)
        finally:
            self.context.producer_done.set()


class ConsumerPool:
    def __init__(self, context: PipelineRuntimeContext, deps: PipelineRuntimeDependencies) -> None:
        self.context = context
        self.deps = deps

    async def run(self) -> None:
        logger.info("[Pipeline] Consumer workers: %s", self.context.consumer_workers)
        queue_size = max(
            self.context.consumer_workers * 2,
            self.context.consumer_workers * config.pipeline.batch_flush_size,
        )
        task_queue: asyncio.Queue[URLTask | None] = asyncio.Queue(maxsize=queue_size)
        summary_lock = asyncio.Lock()

        await asyncio.gather(
            self._feeder(task_queue),
            *(self._worker(task_queue, summary_lock) for _ in range(self.context.consumer_workers)),
        )

    async def _feeder(self, task_queue: asyncio.Queue[Any | None]) -> None:
        while True:
            batch = await self.context.channel.fetch(
                max_items=config.pipeline.batch_fetch_size,
                timeout_s=config.pipeline.fetch_timeout_s,
            )
            if not batch:
                if self.context.producer_done.is_set():
                    break
                continue
            for task in batch:
                await task_queue.put(task)

        for _ in range(self.context.consumer_workers):
            await task_queue.put(None)

    async def _worker(
        self,
        task_queue: asyncio.Queue[Any | None],
        summary_lock: asyncio.Lock,
    ) -> None:
        session = self.deps.browser_session_factory(
            headless=self.context.headless,
            guard_intervention_mode=self.context.guard_intervention_mode,
            guard_thread_id=self.context.guard_thread_id,
        )
        await session.start()
        extractor = self.deps.detail_page_worker_cls(
            page=session.page,
            fields=self.context.fields,
            output_dir=self.context.output_dir,
            skill_runtime=self.context.skill_runtime,
        )
        try:
            while True:
                task = await task_queue.get()
                if task is None:
                    return
                await self.deps.process_task(
                    extractor=extractor,
                    task=task,
                    run_records=self.context.run_records,
                    summary_lock=summary_lock,
                    state=self.context.state,
                    tracker=self.context.tracker,
                )
        finally:
            await session.stop()


@dataclass(slots=True)
class PipelineServiceBundle:
    producer: ProducerService
    consumer_pool: ConsumerPool


def create_pipeline_services(
    context: PipelineRuntimeContext,
    deps: PipelineRuntimeDependencies,
) -> PipelineServiceBundle:
    return PipelineServiceBundle(
        producer=ProducerService(context, deps),
        consumer_pool=ConsumerPool(context, deps),
    )
