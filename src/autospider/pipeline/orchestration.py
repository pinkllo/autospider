"""Pipeline orchestration helpers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from ..common.browser.intervention import BrowserInterventionRequired
from ..common.channel.base import URLChannel, URLTask
from ..common.config import config
from ..common.experience import SkillRuntime
from ..common.logger import get_logger
from ..domain.fields import FieldDefinition
from .progress_tracker import TaskProgressTracker

logger = get_logger(__name__)


async def _set_runtime_stage(
    tracker: TaskProgressTracker,
    *,
    stage: str,
    terminal_reason: str = "",
) -> None:
    payload = {"stage": stage}
    if terminal_reason:
        payload["terminal_reason"] = terminal_reason
    await tracker.set_runtime_state(payload)


@dataclass(slots=True)
class PipelineRuntimeState:
    collection_config: dict[str, Any] = field(default_factory=dict)
    extraction_config: dict[str, Any] = field(default_factory=dict)
    validation_failures: list[dict[str, Any]] = field(default_factory=list)
    extraction_evidence: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    terminal_reason: str = ""


@dataclass(slots=True)
class PipelineSessionBundle:
    list_session: Any

    async def start(self) -> None:
        await self.list_session.start()

    async def stop(self) -> None:
        await self.list_session.stop()


@dataclass(slots=True)
class PipelineRuntimeContext:
    list_url: str
    anchor_url: str | None
    page_state_signature: str
    variant_label: str | None
    task_description: str
    execution_brief: dict[str, Any]
    fields: list[FieldDefinition]
    output_dir: str
    headless: bool | None
    explore_count: int
    validate_count: int
    consumer_workers: int
    max_pages: int | None
    target_url_count: int | None
    guard_intervention_mode: str
    guard_thread_id: str
    selected_skills: list[dict[str, str]] | None
    channel: URLChannel
    run_records: dict[str, dict]
    summary: dict[str, Any]
    tracker: TaskProgressTracker
    skill_runtime: SkillRuntime
    sessions: PipelineSessionBundle
    plan_knowledge: str = ""
    task_plan_snapshot: dict[str, Any] = field(default_factory=dict)
    plan_journal: list[dict[str, Any]] = field(default_factory=list)
    initial_nav_steps: list[dict[str, Any]] = field(default_factory=list)
    url_only_mode: bool = False
    execution_id: str = ""
    resume_mode: str = "fresh"
    global_browser_budget: int | None = None
    runtime_state: PipelineRuntimeState = field(default_factory=PipelineRuntimeState)


@dataclass(frozen=True, slots=True)
class PipelineRuntimeDependencies:
    browser_session_factory: Callable[..., Any]
    collector_cls: type
    detail_page_worker_cls: type
    set_state_error: Callable[[PipelineRuntimeState, str], None]
    process_task: Callable[..., Awaitable[None]]


class ProducerService:
    def __init__(self, context: PipelineRuntimeContext, deps: PipelineRuntimeDependencies) -> None:
        self.context = context
        self.deps = deps

    async def _release_list_session(self) -> None:
        logger.info("[Pipeline] 释放列表页浏览器会话，准备进入详情抽取阶段")
        await self.context.sessions.list_session.stop()

    async def run(self) -> None:
        try:
            await _set_runtime_stage(self.context.tracker, stage="collecting")
            collector = self.deps.collector_cls(
                page=self.context.sessions.list_session.page,
                list_url=self.context.list_url,
                task_description=self.context.task_description,
                execution_brief=dict(self.context.execution_brief or {}),
                explore_count=self.context.explore_count,
                output_dir=self.context.output_dir,
                url_channel=self.context.channel,
                target_url_count=self.context.target_url_count,
                max_pages=self.context.max_pages,
                persist_progress=False,
                skill_runtime=self.context.skill_runtime,
                selected_skills=self.context.selected_skills,
                initial_nav_steps=list(self.context.initial_nav_steps or []),
            )
            result = await collector.run()
            self.context.summary["collected_urls"] = len(result.collected_urls)
            common_detail_xpath = getattr(collector, "common_detail_xpath", None)
            if common_detail_xpath is not None:
                common_detail_xpath = str(common_detail_xpath).strip() or None
            self.context.runtime_state.collection_config = {
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
                "anchor_url": str(self.context.anchor_url or ""),
                "page_state_signature": str(self.context.page_state_signature or ""),
                "variant_label": str(self.context.variant_label or ""),
                "task_description": self.context.task_description,
            }
            logger.info("[Pipeline] URL 收集完成: collected_urls=%s", len(result.collected_urls))
            await self._release_list_session()
            await self.context.tracker.set_total(len(result.collected_urls))
            await self.context.channel.seal()
        except BrowserInterventionRequired:
            raise
        except Exception as exc:  # noqa: BLE001
            self.deps.set_state_error(self.context.runtime_state, f"producer_error: {exc}")
            self.context.runtime_state.terminal_reason = "producer_error"
            await self.context.channel.close_with_error(f"producer_error: {exc}")
            logger.info("[Pipeline] Producer failed: %s", exc)


class ConsumerPool:
    def __init__(self, context: PipelineRuntimeContext, deps: PipelineRuntimeDependencies) -> None:
        self.context = context
        self.deps = deps
        self._claim_slots: asyncio.Semaphore | None = None
        self._entered_consuming = False

    async def run(self) -> None:
        logger.info("[Pipeline] Consumer workers: %s", self.context.consumer_workers)
        queue_size = max(
            self.context.consumer_workers * 2,
            self.context.consumer_workers * config.pipeline.batch_flush_size,
        )
        task_queue: asyncio.Queue[URLTask | None] = asyncio.Queue(maxsize=queue_size)
        summary_lock = asyncio.Lock()
        self._claim_slots = asyncio.Semaphore(max(1, self.context.consumer_workers))

        await asyncio.gather(
            self._feeder(task_queue),
            *(self._worker(task_queue, summary_lock) for _ in range(self.context.consumer_workers)),
        )

    async def _fetch_one_task(self) -> list[URLTask]:
        if self._claim_slots is None:
            raise RuntimeError("consumer_claim_slots_uninitialized")

        await self._claim_slots.acquire()
        batch = await self.context.channel.fetch(
            max_items=1,
            timeout_s=config.pipeline.fetch_timeout_s,
        )
        if batch:
            return batch

        self._claim_slots.release()
        return []

    def _release_claim_slot(self) -> None:
        if self._claim_slots is None:
            raise RuntimeError("consumer_claim_slots_uninitialized")
        self._claim_slots.release()

    async def _feeder(self, task_queue: asyncio.Queue[Any | None]) -> None:
        while True:
            batch = await self._fetch_one_task()
            if not batch:
                if await self.context.channel.is_drained():
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
        logger.info("[Pipeline] Consumer worker 准备启动详情页浏览器")
        session = self.deps.browser_session_factory(
            headless=self.context.headless,
            guard_intervention_mode=self.context.guard_intervention_mode,
            guard_thread_id=self.context.guard_thread_id,
            budget_key=self.context.execution_id,
            global_browser_budget=self.context.global_browser_budget,
        )
        await session.start()
        logger.info("[Pipeline] Consumer worker 浏览器已启动")
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
                if not self._entered_consuming:
                    self._entered_consuming = True
                    await _set_runtime_stage(self.context.tracker, stage="consuming")
                try:
                    await self.deps.process_task(
                        extractor=extractor,
                        task=task,
                        execution_id=self.context.execution_id,
                        run_records=self.context.run_records,
                        summary_lock=summary_lock,
                        state=self.context.runtime_state,
                        tracker=self.context.tracker,
                    )
                finally:
                    self._release_claim_slot()
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
