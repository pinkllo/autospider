from __future__ import annotations

import pytest

import autospider.common.config as config_module
from autospider.common.channel import __all__ as channel_exports
from autospider.common.channel.factory import create_url_channel
from autospider.common.channel.redis_channel import RedisURLChannel
from autospider.pipeline.helpers import build_execution_context
from autospider.pipeline.types import ExecutionRequest, PipelineMode


def _reset_config_cache() -> None:
    config_module._CONFIG_CACHE = None


@pytest.mark.parametrize("legacy_mode", ["memory", "file"])
def test_execution_request_rejects_legacy_pipeline_modes(legacy_mode: str) -> None:
    with pytest.raises(ValueError):
        ExecutionRequest.from_params({"pipeline_mode": legacy_mode})


def test_build_execution_context_defaults_to_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PIPELINE_MODE", raising=False)
    _reset_config_cache()

    request = ExecutionRequest.from_params({})

    assert request.pipeline_mode is PipelineMode.REDIS

    context = build_execution_context(request)

    assert context.pipeline_mode is PipelineMode.REDIS


def test_execution_request_normalizes_blank_pipeline_mode_to_redis() -> None:
    request = ExecutionRequest.from_params({"pipeline_mode": "  "})

    assert request.pipeline_mode is PipelineMode.REDIS


@pytest.mark.parametrize("legacy_mode", ["memory", "file"])
def test_create_url_channel_rejects_legacy_modes(legacy_mode: str) -> None:
    with pytest.raises(ValueError, match="pipeline_mode_only_supports_redis"):
        create_url_channel(mode=legacy_mode)


def test_create_url_channel_accepts_redis() -> None:
    channel = create_url_channel(mode="redis")

    assert isinstance(channel, RedisURLChannel)


def test_common_channel_stops_exporting_legacy_channels() -> None:
    assert "MemoryURLChannel" not in channel_exports
    assert "FileURLChannel" not in channel_exports
