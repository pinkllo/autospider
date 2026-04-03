"""Pipeline orchestration helpers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..common.browser.intervention import BrowserInterventionRequired
from ..common.channel.base import URLChannel, URLTask
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
    staged_records: dict[str, dict]
    summary: dict[str, Any]
    tracker: TaskProgressTracker
    skill_runtime: SkillRuntime
    sessions: PipelineSessionBundle
    staging_dir: Path
    url_only_mode: bool = False
    producer_done: asyncio.Event = field(default_factory=asyncio.Event)
    xpath_ready: asyncio.Event = field(default_factory=asyncio.Event)
    state: dict[str, object] = field(default_factory=lambda: {"fields_config": None, "error": None})
    explore_tasks: list[URLTask] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PipelineRuntimeDependencies:
    browser_session_factory: Callable[..., Any]
    collector_cls: type
    batch_field_extractor_cls: type
    batch_xpath_extractor_cls: type
    prepare_fields_config: Callable[[list[dict]], tuple[list[dict], list[str], list[str]]]
    set_state_error: Callable[[dict[str, object], str], None]
    collect_tasks: Callable[[URLChannel, int, asyncio.Event], Awaitable[list[URLTask]]]
    process_task: Callable[..., Awaitable[None]]
    fail_tasks: Callable[[list[URLTask], str], Awaitable[None]]


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
            await self.context.tracker.set_total(len(result.collected_urls))
        except BrowserInterventionRequired:
            raise
        except Exception as exc:  # noqa: BLE001
            self.deps.set_state_error(self.context.state, f"producer_error: {exc}")
            logger.info("[Pipeline] Producer failed: %s", exc)
        finally:
            self.context.producer_done.set()
            await self.context.channel.close()


class ExplorationService:
    def __init__(self, context: PipelineRuntimeContext, deps: PipelineRuntimeDependencies) -> None:
        self.context = context
        self.deps = deps

    async def run(self) -> None:
        if self.context.url_only_mode:
            logger.info("[Pipeline] 未提供字段定义，启用 URL-only 模式。")
            self.context.state["fields_config"] = [
                {
                    "name": "url",
                    "description": "详情页 URL",
                    "xpath": None,
                    "required": True,
                    "data_type": "url",
                    "extraction_source": "task_url",
                }
            ]
            self.context.xpath_ready.set()
            return

        needed = self.context.explore_count + self.context.validate_count
        tasks = await self.deps.collect_tasks(
            channel=self.context.channel,
            needed=needed,
            producer_done=self.context.producer_done,
        )
        self.context.explore_tasks.extend(tasks)
        urls = [task.url for task in tasks if task.url]

        if not urls:
            self.deps.set_state_error(self.context.state, "no_urls_for_exploration")
            logger.info("[Pipeline] No URLs collected for exploration.")
            self.context.xpath_ready.set()
            return

        extractor = self.deps.batch_field_extractor_cls(
            page=self.context.sessions.detail_session.page,
            fields=self.context.fields,
            explore_count=self.context.explore_count,
            validate_count=self.context.validate_count,
            output_dir=self.context.output_dir,
            skill_runtime=self.context.skill_runtime,
        )
        result = await extractor.run(urls=urls)
        raw_fields_config = result.to_extraction_config().get("fields", [])
        fields_config, missing_required, missing_optional = self.deps.prepare_fields_config(
            raw_fields_config
        )

        if missing_optional:
            logger.info("[Pipeline] Optional fields missing XPath and will be skipped: %s", missing_optional)

        if missing_required:
            self.deps.set_state_error(
                self.context.state,
                f"required_fields_xpath_missing: {', '.join(missing_required)}",
            )
            logger.info("[Pipeline] Required fields missing XPath: %s", missing_required)
            self.context.state["fields_config"] = []
            self.context.xpath_ready.set()
            return
        if not fields_config:
            self.deps.set_state_error(self.context.state, "no_valid_fields_config")
            logger.info("[Pipeline] No valid fields config generated from exploration.")

        self.context.state["fields_config"] = fields_config
        self.context.xpath_ready.set()


class ConsumerPool:
    def __init__(self, context: PipelineRuntimeContext, deps: PipelineRuntimeDependencies) -> None:
        self.context = context
        self.deps = deps

    async def run(self) -> None:
        await self.context.xpath_ready.wait()
        fields_config = self.context.state.get("fields_config") or []
        if not fields_config:
            fail_reason = str(self.context.state.get("error") or "xpath_config_missing")
            await self.deps.fail_tasks(self.context.explore_tasks, fail_reason)
            return

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

    async def _feeder(self, task_queue: asyncio.Queue[URLTask | None]) -> None:
        for task in self.context.explore_tasks:
            await task_queue.put(task)

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
        task_queue: asyncio.Queue[URLTask | None],
        summary_lock: asyncio.Lock,
    ) -> None:
        session = self.deps.browser_session_factory(
            headless=self.context.headless,
            guard_intervention_mode=self.context.guard_intervention_mode,
            guard_thread_id=self.context.guard_thread_id,
        )
        await session.start()
        extractor = self.deps.batch_xpath_extractor_cls(
            page=session.page,
            fields_config=self.context.state.get("fields_config") or [],
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
                    staging_dir=self.context.staging_dir,
                    staged_records=self.context.staged_records,
                    summary_lock=summary_lock,
                    tracker=self.context.tracker,
                )
        finally:
            await session.stop()


@dataclass(slots=True)
class PipelineServiceBundle:
    producer: ProducerService
    exploration: ExplorationService
    consumer_pool: ConsumerPool


def create_pipeline_services(
    context: PipelineRuntimeContext,
    deps: PipelineRuntimeDependencies,
) -> PipelineServiceBundle:
    return PipelineServiceBundle(
        producer=ProducerService(context, deps),
        exploration=ExplorationService(context, deps),
        consumer_pool=ConsumerPool(context, deps),
    )
