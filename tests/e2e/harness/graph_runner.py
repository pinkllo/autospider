from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from importlib import import_module
from pathlib import Path
from typing import Any
from uuid import uuid4

from tests.e2e.contracts import GraphE2ECase

from .errors import (
    GraphHarnessError,
    MissingClarificationAnswerError,
    UnsupportedInterruptError,
)
from .io import load_json_object, load_jsonl_records, resolve_output_files
from .models import GraphHarnessResult
from .normalize import normalize_records, normalize_summary


class GraphRunnerE2EHarness:
    """Drive chat_pipeline end-to-end through GraphRunner.invoke/resume."""

    def __init__(self, *, runner_factory: Callable[[], Any] | None = None) -> None:
        self._runner_factory = runner_factory

    async def run_case(
        self,
        *,
        case: GraphE2ECase,
        base_url: str,
        output_dir: Path | str,
        cli_args: Mapping[str, Any] | None = None,
        thread_id: str | None = None,
    ) -> GraphHarnessResult:
        return await self.run_chat_pipeline(
            request_text=case.materialize_request_text(base_url=base_url),
            override_task=case.materialize_override_task(base_url=base_url),
            clarification_answers=case.materialize_answers(base_url=base_url),
            output_dir=output_dir,
            cli_args=cli_args,
            thread_id=thread_id,
        )

    async def run_chat_pipeline(
        self,
        *,
        request_text: str,
        override_task: Mapping[str, Any],
        output_dir: Path | str,
        clarification_answers: Sequence[str] = (),
        cli_args: Mapping[str, Any] | None = None,
        thread_id: str | None = None,
    ) -> GraphHarnessResult:
        resolved_output_dir = Path(output_dir)
        resolved_thread_id = str(thread_id or uuid4().hex)
        runner = self._build_runner()
        graph_input = self._build_graph_input(
            request_text=request_text,
            output_dir=resolved_output_dir,
            cli_args=cli_args,
            thread_id=resolved_thread_id,
            clarification_answers=clarification_answers,
        )
        initial_result = await runner.invoke(graph_input)
        final_result = await self._drive_interrupts(
            runner=runner,
            initial_result=self._model_dump(initial_result),
            clarification_answers=clarification_answers,
            override_task=override_task,
        )
        if not _is_success_result(final_result):
            return GraphHarnessResult(graph_result=final_result)
        output_files = resolve_output_files(graph_result=final_result, output_dir=resolved_output_dir)
        raw_records = load_jsonl_records(output_files.merged_results_path)
        raw_summary = load_json_object(output_files.merged_summary_path)
        return GraphHarnessResult(
            graph_result=final_result,
            output_files=output_files,
            raw_records=raw_records,
            raw_summary=raw_summary,
            normalized_records=normalize_records(raw_records),
            normalized_summary=normalize_summary(raw_summary),
        )

    def _build_runner(self) -> Any:
        if self._runner_factory is not None:
            return self._runner_factory()
        _, graph_runner_cls = _load_graph_types()
        return graph_runner_cls()

    def _build_graph_input(
        self,
        *,
        request_text: str,
        output_dir: Path,
        cli_args: Mapping[str, Any] | None,
        thread_id: str,
        clarification_answers: Sequence[str],
    ) -> Any:
        graph_input_cls, _ = _load_graph_types()
        resolved_cli_args = _build_cli_args(
            request_text=request_text,
            output_dir=output_dir,
            cli_args=cli_args,
            clarification_answers=clarification_answers,
        )
        return graph_input_cls(
            entry_mode="chat_pipeline",
            cli_args=resolved_cli_args,
            thread_id=thread_id,
        )

    async def _drive_interrupts(
        self,
        *,
        runner: Any,
        initial_result: Mapping[str, Any],
        clarification_answers: Sequence[str],
        override_task: Mapping[str, Any],
    ) -> dict[str, Any]:
        remaining_answers = list(clarification_answers)
        current = dict(initial_result)
        while str(current.get("status") or "") == "interrupted":
            payload = _primary_interrupt_payload(current)
            resume_payload = self._resume_payload(
                payload=payload,
                remaining_answers=remaining_answers,
                override_task=override_task,
            )
            thread_id = str(current.get("thread_id") or "").strip()
            if not thread_id:
                raise GraphHarnessError("graph result missing thread_id during resume")
            resumed = await runner.resume(
                thread_id=thread_id,
                resume=resume_payload,
                use_command=True,
            )
            current = self._model_dump(resumed)
        return current

    def _resume_payload(
        self,
        *,
        payload: Mapping[str, Any],
        remaining_answers: list[str],
        override_task: Mapping[str, Any],
    ) -> dict[str, Any]:
        interrupt_type = str(payload.get("type") or "").strip().lower()
        if interrupt_type == "chat_clarification":
            return _resume_clarification(
                payload=payload,
                remaining_answers=remaining_answers,
            )
        if interrupt_type == "chat_review":
            return {
                "action": "override_task",
                "task": deepcopy(dict(override_task)),
            }
        if interrupt_type in {"browser_intervention", "history_task_select"}:
            raise UnsupportedInterruptError(interrupt_type, dict(payload))
        raise UnsupportedInterruptError(interrupt_type or "<missing>", dict(payload))

    @staticmethod
    def _model_dump(result: Any) -> dict[str, Any]:
        if hasattr(result, "model_dump"):
            payload = result.model_dump()
        elif isinstance(result, Mapping):
            payload = dict(result)
        else:
            raise GraphHarnessError(f"unsupported graph result type: {type(result)!r}")
        return {str(key): value for key, value in dict(payload).items()}


def _load_graph_types() -> tuple[Any, Any]:
    module = import_module("autospider.graph")
    return getattr(module, "GraphInput"), getattr(module, "GraphRunner")


def _build_cli_args(
    *,
    request_text: str,
    output_dir: Path,
    cli_args: Mapping[str, Any] | None,
    clarification_answers: Sequence[str],
) -> dict[str, Any]:
    resolved = dict(cli_args or {})
    resolved["request"] = request_text
    resolved["output_dir"] = str(output_dir)
    if "max_turns" not in resolved:
        resolved["max_turns"] = max(3, len(clarification_answers) + 1)
    return resolved


def _is_success_result(result: Mapping[str, Any]) -> bool:
    return str(result.get("status") or "").strip().lower() == "success"


def _primary_interrupt_payload(result: Mapping[str, Any]) -> dict[str, Any]:
    for item in list(result.get("interrupts") or []):
        if not isinstance(item, Mapping):
            continue
        payload = item.get("value")
        if isinstance(payload, Mapping):
            return {str(key): value for key, value in payload.items()}
    raise GraphHarnessError("graph result is interrupted but contains no interrupt payload")


def _resume_clarification(
    *,
    payload: Mapping[str, Any],
    remaining_answers: list[str],
) -> dict[str, Any]:
    if not remaining_answers:
        raise MissingClarificationAnswerError(
            question=str(payload.get("question") or ""),
            index=int(payload.get("turn") or 0),
        )
    return {"answer": remaining_answers.pop(0)}
