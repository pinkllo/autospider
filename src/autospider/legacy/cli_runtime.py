from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DoctorCheckResult:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class DoctorCheckSection:
    name: str
    title: str
    checks: tuple[DoctorCheckResult, ...]


def bootstrap_cli_logging(*, output_dir: str | None = None) -> None:
    from autospider.platform.observability.logger import bootstrap_logging

    bootstrap_logging(output_dir=output_dir)


def init_database(*, reset: bool = False) -> None:
    from .common.db.engine import init_db

    init_db(reset=reset)


def get_default_serial_mode() -> bool:
    from autospider.platform.config.runtime import config

    return bool(config.pipeline.local_serial_mode)


def load_graph_runtime():
    from .graph import GraphInput, GraphRunner

    return GraphInput, GraphRunner


def build_field_definition(payload: dict[str, Any]):
    from .domain.fields import build_field_definitions

    return build_field_definitions([payload])[0]


def build_field_definitions(payloads: list[dict[str, Any]]):
    from .domain.fields import build_field_definitions as _build_field_definitions

    return _build_field_definitions(item for item in payloads if isinstance(item, dict))


def create_field_definition(**payload: Any):
    from .domain.fields import FieldDefinition

    return FieldDefinition(**payload)


def serialize_field_definitions_payload(fields: list[Any]) -> list[dict[str, Any]]:
    from .domain.fields import serialize_field_definitions

    return serialize_field_definitions(fields)


def build_doctor_sections() -> list[DoctorCheckSection]:
    return [
        DoctorCheckSection(
            name="core",
            title="Core Status",
            checks=tuple(run_doctor_checks()),
        ),
        DoctorCheckSection(
            name="runtime",
            title="Runtime Status",
            checks=tuple(_collect_runtime_checks()),
        ),
    ]


def run_doctor_checks() -> list[DoctorCheckResult]:
    return [
        _check_database(),
        _check_redis(),
        _check_graph_checkpoint(),
    ]


def _collect_runtime_checks() -> list[DoctorCheckResult]:
    return [
        _check_runtime_log_path(),
        _check_llm_trace_path(),
    ]


def _check_runtime_log_path() -> DoctorCheckResult:
    from autospider.platform.observability.logger import _resolve_runtime_log_file

    try:
        return DoctorCheckResult(
            name="runtime_log",
            status="ok",
            detail=str(_resolve_runtime_log_file()),
        )
    except Exception as exc:  # noqa: BLE001
        return DoctorCheckResult(name="runtime_log", status="fail", detail=str(exc))


def _check_llm_trace_path() -> DoctorCheckResult:
    from autospider.platform.config.runtime import get_config
    from .common.llm.trace_logger import _resolve_trace_path

    try:
        runtime_config = get_config(reload=True)
        trace_path = _resolve_trace_path(runtime_config.llm.trace_file)
        if runtime_config.llm.trace_enabled:
            return DoctorCheckResult(
                name="llm_trace",
                status="ok",
                detail=str(trace_path),
            )
        return DoctorCheckResult(
            name="llm_trace",
            status="skipped",
            detail=f"LLM_TRACE_ENABLED=false | {trace_path}",
        )
    except Exception as exc:  # noqa: BLE001
        return DoctorCheckResult(name="llm_trace", status="fail", detail=str(exc))


def _check_database() -> DoctorCheckResult:
    from autospider.platform.config.runtime import config
    from .common.db.engine import get_engine

    try:
        engine = get_engine()
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
        return DoctorCheckResult(
            name="database",
            status="ok",
            detail=str(config.database.url or ""),
        )
    except Exception as exc:  # noqa: BLE001
        return DoctorCheckResult(name="database", status="fail", detail=str(exc))


def _check_redis() -> DoctorCheckResult:
    from autospider.platform.config.runtime import config
    from .common.storage.redis_pool import get_sync_client

    if not config.redis.enabled:
        return DoctorCheckResult(
            name="redis",
            status="fail",
            detail="REDIS_ENABLED=false",
        )

    try:
        client = get_sync_client()
        if client is None:
            raise RuntimeError("Redis client unavailable")
        client.ping()
        return DoctorCheckResult(
            name="redis",
            status="ok",
            detail=f"{config.redis.host}:{config.redis.port}/{config.redis.db}",
        )
    except Exception as exc:  # noqa: BLE001
        return DoctorCheckResult(name="redis", status="fail", detail=str(exc))


def _check_graph_checkpoint() -> DoctorCheckResult:
    from autospider.platform.config.runtime import config
    from .graph.checkpoint import graph_checkpoint_enabled, graph_checkpointer_session

    if not graph_checkpoint_enabled():
        return DoctorCheckResult(
            name="graph_checkpoint",
            status="skipped",
            detail="GRAPH_CHECKPOINT_ENABLED=false",
        )

    async def _probe_checkpoint() -> None:
        async with graph_checkpointer_session() as _checkpointer:
            return None

    try:
        asyncio.run(_probe_checkpoint())
        backend = str(config.graph_checkpoint.backend or "redis")
        return DoctorCheckResult(
            name="graph_checkpoint",
            status="ok",
            detail=backend,
        )
    except Exception as exc:  # noqa: BLE001
        return DoctorCheckResult(name="graph_checkpoint", status="fail", detail=str(exc))
