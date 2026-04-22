"""Helpers for aggregating LLM trace stats for a single graph run."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autospider.platform.config.runtime import config
from autospider.platform.shared_kernel.utils.paths import resolve_repo_path


@dataclass(frozen=True, slots=True)
class LLMTraceStats:
    llm_calls: int = 0
    calls_with_token_usage: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    token_usage_available: bool = False

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "llm_calls": self.llm_calls,
            "calls_with_token_usage": self.calls_with_token_usage,
            "token_usage_available": self.token_usage_available,
        }
        if self.token_usage_available:
            payload.update(
                {
                    "prompt_tokens": self.prompt_tokens,
                    "completion_tokens": self.completion_tokens,
                    "total_tokens": self.total_tokens,
                }
            )
        return payload


def collect_trace_stats(*, run_id: str, trace_id: str = "", trace_file: str = "") -> LLMTraceStats:
    path = _resolve_trace_path(trace_file or config.llm.trace_file)
    if not path.exists():
        return LLMTraceStats()
    llm_calls = 0
    calls_with_usage = 0
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    for record in _iter_matching_records(path, run_id=run_id, trace_id=trace_id):
        llm_calls += 1
        usage = _read_usage(record)
        if usage is None:
            continue
        calls_with_usage += 1
        prompt_tokens += int(usage.get("prompt_tokens", 0) or 0)
        completion_tokens += int(usage.get("completion_tokens", 0) or 0)
        total_tokens += int(usage.get("total_tokens", 0) or 0)
    return LLMTraceStats(
        llm_calls=llm_calls,
        calls_with_token_usage=calls_with_usage,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        token_usage_available=calls_with_usage > 0,
    )


def _resolve_trace_path(raw_path: str) -> Path:
    target = str(raw_path or "").strip() or "output/llm_trace.jsonl"
    return resolve_repo_path(target)


def _iter_matching_records(path: Path, *, run_id: str, trace_id: str) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    resolved_run_id = str(run_id or "").strip()
    resolved_trace_id = str(trace_id or "").strip()
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            record_run_id = str(record.get("run_id") or "").strip()
            record_trace_id = str(record.get("trace_id") or "").strip()
            if resolved_run_id and record_run_id == resolved_run_id:
                matched.append(record)
                continue
            if resolved_trace_id and record_trace_id == resolved_trace_id:
                matched.append(record)
    return matched


def _read_usage(record: dict[str, Any]) -> dict[str, Any] | None:
    response_summary = record.get("response_summary")
    if not isinstance(response_summary, dict):
        return None
    usage = response_summary.get("token_usage")
    if not isinstance(usage, dict):
        return None
    return usage

