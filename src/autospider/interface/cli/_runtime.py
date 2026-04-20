from __future__ import annotations

import asyncio
import importlib
import json
import logging
import threading
from typing import Any

from autospider.composition.use_cases.resume import ResumeRun
from autospider.composition.use_cases.run_chat_pipeline import RunChatPipeline

logger = logging.getLogger(__name__)


class CliRuntimeProxy:
    def __init__(self) -> None:
        object.__setattr__(self, "_overrides", {})

    def __getattr__(self, name: str) -> Any:
        overrides = object.__getattribute__(self, "_overrides")
        if name in overrides:
            return overrides[name]
        module = importlib.import_module("autospider.legacy.cli_runtime")
        return getattr(module, name)

    def __setattr__(self, name: str, value: Any) -> None:
        object.__getattribute__(self, "_overrides")[name] = value

    def __delattr__(self, name: str) -> None:
        overrides = object.__getattribute__(self, "_overrides")
        if name in overrides:
            del overrides[name]
            return
        module = importlib.import_module("autospider.legacy.cli_runtime")
        delattr(module, name)


cli_runtime = CliRuntimeProxy()


def run_async_safely(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    return _run_in_thread(coro)


def invoke_graph(
    entry_mode: str, cli_args: dict[str, Any], *, thread_id: str = ""
) -> dict[str, Any]:
    if entry_mode != "chat_pipeline":
        raise ValueError(f"unsupported entry mode: {entry_mode}")
    _ensure_database_ready()
    graph_result = run_async_safely(
        RunChatPipeline().run(cli_args=dict(cli_args), thread_id=thread_id)
    )
    result = graph_result.model_dump()
    _log_graph_runtime(result)
    return result


def inspect_graph(thread_id: str) -> dict[str, Any]:
    _ensure_database_ready()
    result = run_async_safely(ResumeRun().inspect(thread_id=thread_id)).model_dump()
    _log_graph_runtime(result)
    return result


def resume_graph(
    thread_id: str,
    *,
    resume: object = None,
    use_command: bool = True,
) -> dict[str, Any]:
    _ensure_database_ready()
    result = run_async_safely(
        ResumeRun().resume(thread_id=thread_id, resume=resume, use_command=use_command)
    ).model_dump()
    _log_graph_runtime(result)
    return result


def parse_resume_payload(resume_json: str) -> tuple[object, bool]:
    payload_text = str(resume_json or "").strip()
    if not payload_text:
        return None, False
    return json.loads(payload_text), True


def raise_if_graph_failed(result: dict[str, Any]) -> None:
    status = str(result.get("status") or "")
    if status != "failed":
        return
    error = result.get("error") or {}
    if isinstance(error, dict):
        message = str(error.get("message") or "图执行失败")
        code = str(error.get("code") or "")
        if code:
            raise RuntimeError(f"{code}: {message}")
        raise RuntimeError(message)
    raise RuntimeError("图执行失败")


def _ensure_database_ready() -> None:
    cli_runtime.init_database()


def _log_graph_runtime(result: dict[str, Any]) -> None:
    thread_id = str(result.get("thread_id") or "")
    checkpoint_id = str(result.get("checkpoint_id") or "")
    status = str(result.get("status") or "")
    if not thread_id:
        return
    message = f"[Graph] thread_id={thread_id}"
    if checkpoint_id:
        message += f", checkpoint_id={checkpoint_id}"
    message += f", status={status or 'unknown'}"
    logger.info(message)


def _run_in_thread(coro: Any) -> Any:
    result_holder: dict[str, object] = {"result": None, "error": None}

    def _runner() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result_holder["result"] = loop.run_until_complete(coro)
        except Exception as exc:  # noqa: BLE001
            result_holder["error"] = exc
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.run_until_complete(loop.shutdown_default_executor())
            loop.close()
            asyncio.set_event_loop(None)

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    if result_holder["error"] is not None:
        raise result_holder["error"]  # type: ignore[misc]
    return result_holder["result"]
