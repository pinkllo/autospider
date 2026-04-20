from __future__ import annotations

import asyncio
import json
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import patch

from autospider.contexts.collection.infrastructure.channel.base import URLChannel, URLTask
from autospider.platform.persistence.redis.pipeline_runtime_store import PipelineRuntimeStore
from autospider.legacy.domain.fields import FieldDefinition
from autospider.legacy.pipeline.finalization import (
    DURABILITY_STATE_DURABLE,
    build_run_record,
    classify_pipeline_result as _classify_result_impl,
)
from autospider.legacy.pipeline.helpers import build_execution_context
from autospider.legacy.pipeline.progress_tracker import TaskProgressTracker
from autospider.legacy.pipeline.runner import run_pipeline
from autospider.legacy.pipeline.types import ExecutionRequest, PipelineMode, PipelineRunResult
from .pipeline_artifacts import build_task_plan, persist_snapshot
from .pipeline_fakes import (
    FakeBrowserRuntimeSession,
    FakeDetailPageWorker,
    FakeSkillRuntime,
    FakeURLCollector,
    serve_site,
)

EXECUTION_ID = "contract-run-001"
THREAD_ID = "thread-contract-001"
TASK_DESCRIPTION = "collect contract fixture"


@dataclass(frozen=True)
class ContractRunArtifacts:
    execution_id: str
    page_url: str
    output_dir: Path
    redis_client: Any
    result: PipelineRunResult


@dataclass(slots=True)
class _ContractState:
    execution_id: str
    page_url: str
    output_dir: Path
    redis_client: "_FakeRedisClient"
    records: dict[str, dict[str, Any]]
    pending_count: int = 0

    @property
    def key_prefix(self) -> str:
        return f"autospider:urls:run:{self.execution_id}"

    def queue_state(self) -> dict[str, int]:
        return {
            "stream_length": len(self.redis_client.xrange(f"{self.key_prefix}:stream")),
            "pending_count": self.pending_count,
        }


class _FakeRedisClient:
    def __init__(self) -> None:
        self._hashes: dict[str, dict[str, str]] = {}
        self._streams: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self._stream_ids: dict[str, int] = {}

    def hset(self, key: str, mapping: dict[str, str]) -> None:
        self._hashes.setdefault(key, {}).update(mapping)

    def hgetall(self, key: str) -> dict[str, str]:
        return dict(self._hashes.get(key, {}))

    def xadd(self, key: str, fields: dict[str, str]) -> str:
        index = self._stream_ids.get(key, 0) + 1
        self._stream_ids[key] = index
        stream_id = f"{index}-0"
        self._streams.setdefault(key, []).append((stream_id, dict(fields)))
        return stream_id

    def xrange(self, key: str) -> list[tuple[str, dict[str, str]]]:
        return [(stream_id, dict(fields)) for stream_id, fields in self._streams.get(key, [])]

    def expire(self, key: str, ttl_s: int) -> None:
        _ = key, ttl_s


class _ContractProgressTracker(TaskProgressTracker):
    def __init__(self, execution_id: str, state: _ContractState) -> None:
        self._contract_state = state
        store = PipelineRuntimeStore(client_factory=lambda: state.redis_client)
        super().__init__(execution_id, runtime_store=store)

    def _build_state(self, **kwargs: Any) -> dict[str, Any]:
        payload = super()._build_state(**kwargs)
        runtime_state = dict(payload.get("runtime_state") or {})
        runtime_state["thread_id"] = THREAD_ID
        runtime_state["queue"] = self._contract_state.queue_state()
        payload["runtime_state"] = runtime_state
        payload["thread_id"] = THREAD_ID
        payload["resume_mode"] = str(runtime_state.get("resume_mode") or "fresh")
        payload["stage"] = str(runtime_state.get("stage") or "starting")
        payload["stream_length"] = runtime_state["queue"]["stream_length"]
        payload["pending_count"] = runtime_state["queue"]["pending_count"]
        return payload


class _FakeURLChannel(URLChannel):
    def __init__(self, state: _ContractState) -> None:
        self._state = state
        self._sealed = False
        self._queue: list[tuple[str, str, str]] = []

    async def publish(self, url: str) -> None:
        data_id = f"detail-{len(self._queue) + self._state.pending_count + 1:03d}"
        payload = {"url": url, "created_at": 1710000000, "metadata": {"source": "contracts"}}
        self._state.redis_client.hset(
            f"{self._state.key_prefix}:data",
            mapping={data_id: json.dumps(payload, ensure_ascii=False)},
        )
        stream_id = self._state.redis_client.xadd(
            f"{self._state.key_prefix}:stream",
            {"data_id": data_id},
        )
        self._queue.append((stream_id, data_id, url))

    async def fetch(self, max_items: int, timeout_s: float | None) -> list[URLTask]:
        if not self._queue:
            await asyncio.sleep(0 if timeout_s is None else min(timeout_s, 0.01))
            return []
        batch = [self._queue.pop(0) for _ in range(min(max_items, len(self._queue)))]
        self._state.pending_count += len(batch)
        return [self._wrap_task(data_id, url) for _, data_id, url in batch]

    async def seal(self) -> None:
        self._sealed = True

    async def is_drained(self) -> bool:
        return self._sealed and not self._queue and self._state.pending_count == 0

    async def close(self) -> None:
        self._sealed = True

    def _wrap_task(self, data_id: str, url: str) -> URLTask:
        async def _ack() -> None:
            self._state.pending_count -= 1

        async def _fail(reason: str) -> None:
            _ = reason
            self._state.pending_count -= 1

        async def _release(reason: str) -> None:
            _ = reason
            self._state.pending_count -= 1
            self._queue.append(("released", data_id, url))

        return URLTask(url=url, ack=_ack, fail=_fail, release=_release)


def run_contract_pipeline(tmp_path: Path) -> ContractRunArtifacts:
    output_dir = tmp_path / "output" / EXECUTION_ID
    with serve_site() as page_url:
        state = _ContractState(
            execution_id=EXECUTION_ID,
            page_url=page_url,
            output_dir=output_dir,
            redis_client=_FakeRedisClient(),
            records={},
        )
        context = _build_context(page_url, output_dir)
        with _patched_pipeline(state):
            result = asyncio.run(run_pipeline(context))
    return ContractRunArtifacts(EXECUTION_ID, page_url, output_dir, state.redis_client, result)


def _build_context(page_url: str, output_dir: Path):
    fields = [FieldDefinition(name="title", description="page title")]
    request = ExecutionRequest(
        list_url=page_url,
        site_url=page_url,
        request=TASK_DESCRIPTION,
        task_description=TASK_DESCRIPTION,
        fields=[field.model_dump(mode="python") for field in fields],
        output_dir=str(output_dir),
        headless=True,
        consumer_concurrency=1,
        max_pages=1,
        target_url_count=1,
        pipeline_mode=PipelineMode.REDIS,
        guard_thread_id=THREAD_ID,
        execution_id=EXECUTION_ID,
        plan_knowledge="# Contract Plan\n\n- source: local-http\n- llm: fake\n",
        task_plan_snapshot=build_task_plan(page_url, TASK_DESCRIPTION),
    )
    return build_execution_context(request, fields=fields)


@contextmanager
def _patched_pipeline(state: _ContractState) -> Iterator[None]:
    def tracker_factory(execution_id: str) -> _ContractProgressTracker:
        return _ContractProgressTracker(execution_id, state)

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "autospider.legacy.pipeline.runner.create_url_channel",
                return_value=_FakeURLChannel(state),
            )
        )
        stack.enter_context(
            patch("autospider.legacy.pipeline.runner.TaskProgressTracker", new=tracker_factory)
        )
        stack.enter_context(
            patch(
                "autospider.legacy.pipeline.runner.BrowserRuntimeSession", FakeBrowserRuntimeSession
            )
        )
        stack.enter_context(
            patch("autospider.legacy.pipeline.runner.SkillRuntime", FakeSkillRuntime)
        )
        stack.enter_context(
            patch("autospider.legacy.pipeline.runner.URLCollector", FakeURLCollector)
        )
        stack.enter_context(
            patch("autospider.legacy.pipeline.runner.DetailPageWorker", FakeDetailPageWorker)
        )
        stack.enter_context(
            patch("autospider.legacy.pipeline.runner._persist_run_snapshot", new=persist_snapshot)
        )
        stack.enter_context(
            patch(
                "autospider.legacy.pipeline.runner._load_persisted_run_records",
                new=partial(_load_records, state),
            )
        )
        stack.enter_context(
            patch(
                "autospider.legacy.pipeline.runner._claim_persisted_item",
                new=partial(_claim_record, state),
            )
        )
        stack.enter_context(
            patch(
                "autospider.legacy.pipeline.runner._commit_persisted_item",
                new=partial(_commit_record, state),
            )
        )
        stack.enter_context(
            patch(
                "autospider.legacy.pipeline.runner._fail_persisted_item",
                new=partial(_fail_record, state),
            )
        )
        stack.enter_context(
            patch(
                "autospider.legacy.pipeline.runner._ack_persisted_item",
                new=partial(_ack_record, state),
            )
        )
        stack.enter_context(
            patch(
                "autospider.legacy.pipeline.runner._release_persisted_claim",
                new=partial(_release_claim, state),
            )
        )
        stack.enter_context(
            patch(
                "autospider.legacy.pipeline.runner._persist_pipeline_records", new=_persist_records
            )
        )
        stack.enter_context(
            patch(
                "autospider.legacy.pipeline.runner._classify_pipeline_result",
                new=_classify_pipeline_result,
            )
        )
        stack.enter_context(
            patch(
                "autospider.legacy.pipeline.finalization.promote_pipeline_skill", return_value=None
            )
        )
        yield


def _persist_records(context: Any, records: dict[str, dict[str, Any]]) -> None:
    context.summary["committed_records"] = [
        {"url": str(record.get("url") or ""), "success": bool(record.get("success"))}
        for _, record in sorted(records.items())
    ]


async def _claim_record(
    state: _ContractState, *, execution_id: str, url: str, worker_id: str
) -> dict[str, Any]:
    _ = execution_id, worker_id
    record = build_run_record(
        url=url, item={"url": url}, success=False, failure_reason="", claim_state="claimed"
    )
    state.records[url] = record
    return dict(record)


async def _commit_record(
    state: _ContractState, *, execution_id: str, url: str, item: dict[str, Any], worker_id: str
) -> dict[str, Any]:
    _ = execution_id, worker_id
    record = build_run_record(
        url=url,
        item=item,
        success=True,
        failure_reason="",
        durability_state=DURABILITY_STATE_DURABLE,
        claim_state="committed",
    )
    state.records[url] = record
    return dict(record)


async def _fail_record(
    state: _ContractState,
    *,
    execution_id: str,
    url: str,
    failure_reason: str,
    item: dict[str, Any],
    worker_id: str,
    terminal_reason: str,
    error_kind: str,
) -> dict[str, Any]:
    _ = execution_id, worker_id, error_kind
    record = build_run_record(
        url=url,
        item=item,
        success=False,
        failure_reason=failure_reason,
        terminal_reason=terminal_reason,
        durability_state=DURABILITY_STATE_DURABLE,
        claim_state="failed",
    )
    state.records[url] = record
    return dict(record)


async def _ack_record(state: _ContractState, *, execution_id: str, url: str) -> dict[str, Any]:
    _ = execution_id
    current = dict(state.records[url])
    current["claim_state"] = "acked"
    state.records[url] = current
    return dict(current)


async def _release_claim(
    state: _ContractState, *, execution_id: str, url: str, worker_id: str, terminal_reason: str
) -> None:
    _ = execution_id, url, worker_id, terminal_reason


def _classify_pipeline_result(**kwargs: Any) -> dict[str, Any]:
    return _classify_result_impl(**kwargs)


def _load_records(state: _ContractState, execution_id: str) -> dict[str, dict[str, Any]]:
    _ = execution_id
    return {url: dict(record) for url, record in state.records.items()}
