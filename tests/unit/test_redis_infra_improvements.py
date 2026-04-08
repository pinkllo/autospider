from __future__ import annotations

import pytest

from autospider.common.config import config
from autospider.common.storage import redis_pool
from autospider.contracts import ExecutionRequest, PipelineMode
from autospider.pipeline import runner as pipeline_runner
from autospider.application.helpers import build_execution_context


class _FakePage:
    async def goto(self, *args, **kwargs):
        return None


class _FakeBrowserSession:
    def __init__(self, *args, **kwargs):
        self.page = _FakePage()

    async def start(self):
        return None

    async def stop(self):
        return None


class _ExplodingChannel:
    def __init__(self):
        self.sealed = False

    async def seal(self):
        self.sealed = True

    async def is_drained(self):
        return self.sealed

    async def close_with_error(self, reason: str):
        return None

    async def close(self):
        return None

    async def fetch(self, *args, **kwargs):
        return []


class _NoopTracker:
    def __init__(self, execution_id: str):
        self.execution_id = execution_id

    async def set_total(self, total: int):
        return None

    async def record_success(self, url: str = ""):
        return None

    async def record_failure(self, url: str = "", error: str = ""):
        return None

    async def mark_done(self, final_status: str = "completed"):
        return None


@pytest.mark.asyncio
async def test_run_pipeline_uses_run_scoped_redis_prefix(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    class _FakeCollector:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def run(self):
            return type(
                "_Result",
                (),
                {
                    "collected_urls": [],
                    "plan_upgrade_requested": False,
                    "plan_upgrade_reason": "",
                    "plan_upgrade_site_url": "",
                },
            )()

    def _fake_create_url_channel(**kwargs):
        captured["create_url_channel_kwargs"] = kwargs
        return _ExplodingChannel()

    monkeypatch.setattr(pipeline_runner, "BrowserRuntimeSession", _FakeBrowserSession)
    monkeypatch.setattr(pipeline_runner, "URLCollector", _FakeCollector)
    monkeypatch.setattr(pipeline_runner, "create_url_channel", _fake_create_url_channel)
    monkeypatch.setattr(pipeline_runner, "TaskProgressTracker", _NoopTracker)
    monkeypatch.setattr(pipeline_runner, "_load_persisted_run_records", lambda execution_id: {})
    monkeypatch.setattr(pipeline_runner, "_persist_run_snapshot", lambda **kwargs: None)
    monkeypatch.setattr(pipeline_runner, "_persist_pipeline_records", lambda context, records: None)
    monkeypatch.setattr(pipeline_runner, "_commit_items_file", lambda items_path, records: None)
    monkeypatch.setattr(pipeline_runner, "_write_summary", lambda summary_path, summary: None)
    monkeypatch.setattr(config.pipeline, "mode", "redis", raising=False)
    monkeypatch.setattr(config.redis, "key_prefix", "autospider:urls", raising=False)
    context = build_execution_context(
        ExecutionRequest(
            list_url="https://example.com/list",
            task_description="采集公告",
            request="采集公告",
            fields=[],
            output_dir=str(tmp_path),
            pipeline_mode=PipelineMode.REDIS,
        ),
        fields=[],
    )

    result = await pipeline_runner.run_pipeline(context)

    execution_id = result["execution_id"]
    kwargs = captured["create_url_channel_kwargs"]
    assert kwargs["redis_key_prefix"] == f"autospider:urls:run:{execution_id}"


def test_sync_redis_pool_retries_after_init_failure(monkeypatch):
    redis_pool._SyncPool.close()
    monkeypatch.setattr(config.redis, "enabled", True, raising=False)

    state = {"calls": 0}

    class _FakeConnectionPool:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def disconnect(self):
            return None

    class _FakeRedisClient:
        def __init__(self, connection_pool):
            self.connection_pool = connection_pool

        def ping(self):
            state["calls"] += 1
            if state["calls"] == 1:
                raise RuntimeError("first ping fails")

    import redis as redis_module

    monkeypatch.setattr(redis_module, "ConnectionPool", _FakeConnectionPool)
    monkeypatch.setattr(redis_module, "Redis", _FakeRedisClient)

    first = redis_pool.get_sync_client()
    second = redis_pool.get_sync_client()

    assert first is None
    assert second is not None
    assert state["calls"] == 2
    redis_pool._SyncPool.close()
