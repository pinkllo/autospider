from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autospider.contexts.chat.application.use_cases.advance_dialogue import AdvanceDialogue
from autospider.contexts.chat.application.use_cases.finalize_task import FinalizeTask
from autospider.contexts.chat.application.use_cases.start_clarification import StartClarification
from autospider.contexts.chat.domain.model import ClarificationSession
from autospider.contexts.chat.domain.ports import LLMClarifier, SessionRepository
from autospider.contexts.chat.infrastructure.adapters.llm_clarifier import TaskClarifierAdapter
from autospider.contexts.chat.infrastructure.publishers import (
    CHAT_EVENTS_STREAM,
    TASK_CLARIFIED_EVENT,
    ChatEventPublisher,
)
from autospider.contexts.chat.infrastructure.repositories.session_repository import (
    RedisSessionRepository,
)
from autospider.contexts.collection.infrastructure.publishers import (
    COLLECTION_EVENTS_STREAM,
    COLLECTION_FINALIZED_EVENT,
    CollectionEventPublisher,
)
from autospider.contexts.experience.application.handlers import (
    CollectionFinalizedHandler,
    CollectionFinalizedPayload,
)
from autospider.contexts.experience.application.skill_promotion import SkillSedimenter
from autospider.contexts.experience.infrastructure.publishers import (
    ExperienceEventPublisher,
    SkillSedimentedPayload,
)
from autospider.contexts.experience.infrastructure.repositories.skill_repository import (
    SkillRepository,
)
from autospider.contexts.planning.application.event_handlers import (
    PlanRepositoryFactory,
    TaskClarifiedHandler,
)
from autospider.contexts.planning.application.dto import TaskClarifiedEventDTO
from autospider.contexts.planning.infrastructure.publishers import PlanningEventPublisher
from autospider.contexts.planning.infrastructure.repositories.artifact_store import (
    ArtifactPlanRepository,
)
from autospider.platform.messaging.in_memory import InMemoryMessaging
from autospider.platform.messaging.ports import Event, Messaging
from autospider.platform.messaging.redis_streams import RedisStreamsMessaging
from autospider.platform.persistence.redis.connection import RedisConnectionPool
from autospider.platform.shared_kernel.trace import clear_run_context, set_run_context

from .sagas.collection_saga import CollectionSaga
from .sagas.multi_dispatch_saga import MultiDispatchSaga
from .sagas.recovery_saga import RecoverySaga

_PLANNING_GROUP = "planning"
_EXPERIENCE_GROUP = "experience"


@dataclass(frozen=True, slots=True)
class SubscriptionSpec:
    name: str
    stream: str
    group: str
    consumer: str
    event_type: str
    handler: Callable[[Event], Awaitable[None]]


class _InMemorySessionRepository(SessionRepository):
    def __init__(self) -> None:
        self._sessions: dict[str, ClarificationSession] = {}

    async def get(self, session_id: str) -> ClarificationSession | None:
        return self._sessions.get(session_id)

    async def save(self, session: ClarificationSession) -> None:
        self._sessions[session.session_id] = session


class CompositionContainer:
    def __init__(
        self,
        *,
        messaging: Messaging | None = None,
        session_repository: SessionRepository | None = None,
        clarifier: LLMClarifier | None = None,
        plan_repository_factory: PlanRepositoryFactory | None = None,
        skill_repository: SkillRepository | None = None,
        consumer_name: str = "composition",
    ) -> None:
        self._redis_pool: RedisConnectionPool | None = None
        self._redis_client: Any | None = None
        self.messaging = messaging or self._build_default_messaging()
        self.session_repository = session_repository or self._build_session_repository()
        self.clarifier = clarifier or TaskClarifierAdapter()
        self.plan_repository_factory = plan_repository_factory or _artifact_plan_repository
        self.skill_repository = skill_repository or SkillRepository()

        self.chat_publisher = ChatEventPublisher(self.messaging)
        self.planning_publisher = PlanningEventPublisher(self.messaging)
        self.collection_publisher = CollectionEventPublisher(self.messaging)
        self.experience_publisher = ExperienceEventPublisher(self.messaging)

        self.start_clarification = StartClarification(self.session_repository, self.clarifier)
        self.advance_dialogue = AdvanceDialogue(self.session_repository, self.clarifier)
        self.finalize_task = FinalizeTask(self.session_repository)

        self.task_clarified_handler = TaskClarifiedHandler(self.plan_repository_factory)
        self.collection_finalized_handler = CollectionFinalizedHandler(
            SkillSedimenter(self.skill_repository)
        )

        self.collection_saga = CollectionSaga(self.collection_publisher)
        self.multi_dispatch_saga = MultiDispatchSaga(self.messaging, self.planning_publisher)
        self.recovery_saga = RecoverySaga()
        self.subscriptions = (
            SubscriptionSpec(
                name="planning.task_clarified",
                stream=CHAT_EVENTS_STREAM,
                group=_PLANNING_GROUP,
                consumer=f"{consumer_name}-planning",
                event_type=TASK_CLARIFIED_EVENT,
                handler=self._handle_task_clarified,
            ),
            SubscriptionSpec(
                name="experience.collection_finalized",
                stream=COLLECTION_EVENTS_STREAM,
                group=_EXPERIENCE_GROUP,
                consumer=f"{consumer_name}-experience",
                event_type=COLLECTION_FINALIZED_EVENT,
                handler=self._handle_collection_finalized,
            ),
        )

    async def pump(self, *subscription_names: str) -> int:
        targets = set(subscription_names)
        processed = 0
        for spec in self.subscriptions:
            if targets and spec.name not in targets:
                continue
            processed += await self._process_subscription(spec)
        return processed

    async def close(self) -> None:
        if self._redis_client is not None and hasattr(self._redis_client, "aclose"):
            await self._redis_client.aclose()
        if self._redis_pool is not None:
            await self._redis_pool.close()

    def _build_default_messaging(self) -> Messaging:
        self._redis_pool = RedisConnectionPool()
        self._redis_client = self._redis_pool.get_client()
        return RedisStreamsMessaging(self._redis_client)

    def _build_session_repository(self) -> SessionRepository:
        if isinstance(self.messaging, InMemoryMessaging):
            return _InMemorySessionRepository()
        if self._redis_client is None:
            raise RuntimeError("redis client is not initialized")
        return RedisSessionRepository(self._redis_client)

    async def _process_subscription(self, spec: SubscriptionSpec) -> int:
        processed = 0
        async for event in self.messaging.subscribe(
            spec.stream,
            spec.group,
            spec.consumer,
            block_ms=0,
        ):
            try:
                if event.type == spec.event_type:
                    await spec.handler(event)
                await self.messaging.ack(spec.stream, spec.group, event.id)
                processed += 1
            except Exception as exc:
                await self.messaging.fail(spec.stream, spec.group, event.id, str(exc))
                raise
        return processed

    async def _handle_task_clarified(self, event: Event) -> None:
        payload = TaskClarifiedEventDTO.model_validate(event.payload)
        set_run_context(run_id=event.run_id, trace_id=event.trace_id)
        try:
            result = self.task_clarified_handler.handle(payload)
        finally:
            clear_run_context()
        if result.status != "success" or result.data is None:
            raise RuntimeError(_result_error(result.errors))
        output_dir = payload.output_dir
        await self.planning_publisher.publish_plan_created(
            plan=result.data,
            trace_id=event.trace_id,
            run_id=event.run_id,
            output_dir=output_dir,
        )
        await self.multi_dispatch_saga.dispatch_plan(
            plan=result.data,
            trace_id=event.trace_id,
            run_id=event.run_id,
            output_dir=output_dir,
        )

    async def _handle_collection_finalized(self, event: Event) -> None:
        payload = CollectionFinalizedPayload.model_validate(event.payload)
        skill_path = self.collection_finalized_handler.handle(payload)
        if skill_path is None:
            return
        await self.experience_publisher.publish_skill_sedimented(
            SkillSedimentedPayload(
                skill_path=str(Path(skill_path)),
                source_run_id=str(payload.run_id or ""),
            ),
            trace_id=event.trace_id,
            run_id=event.run_id,
        )


def _artifact_plan_repository(*, site_url: str, user_request: str, output_dir: str):
    return ArtifactPlanRepository(
        site_url=site_url,
        user_request=user_request,
        output_dir=output_dir,
    )


def _result_error(errors: list[Any]) -> str:
    if not errors:
        return "event handler failed"
    first = errors[0]
    message = getattr(first, "message", "") or str(first)
    code = getattr(first, "code", "")
    return f"{code}: {message}".strip(": ")
