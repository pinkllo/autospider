"""Scenario-level evaluation for benchmark runs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .metrics import (
    FieldMetrics,
    RecordMetrics,
    aggregate_field_f1,
    align_records,
    compute_field_metrics,
    compute_record_metrics,
    field_match,
)

DEFAULT_GRAPH_STATUS = "unknown"
MISSING_STEPS_REASON = "total_graph_steps missing for max_steps evaluation"


@dataclass(frozen=True)
class EvaluationParams:
    """Scenario evaluation configuration."""

    match_key: str
    field_matching: dict[str, str]
    thresholds: dict[str, float | int]


@dataclass(frozen=True)
class ScenarioResult:
    """Evaluation output for one scenario."""

    record_metrics: RecordMetrics
    field_metrics: dict[str, FieldMetrics]
    overall_field_f1: float
    exact_match_rate: float
    passed: bool
    graph_status: str
    failure_reasons: list[str] = field(default_factory=list)


def evaluate_scenario(
    *,
    actual_file: Path,
    ground_truth_file: Path,
    params: EvaluationParams,
    execution_summary: dict[str, Any] | None = None,
) -> ScenarioResult:
    """Evaluate actual JSONL output against ground truth JSONL."""
    actual_records = _load_jsonl(actual_file)
    expected_records = _load_jsonl(ground_truth_file)
    record_metrics = compute_record_metrics(
        actual=actual_records,
        expected=expected_records,
        match_key=params.match_key,
    )
    alignment = align_records(
        actual=actual_records,
        expected=expected_records,
        match_key=params.match_key,
    )
    field_metrics = compute_field_metrics(
        actual_records=actual_records,
        expected_records=expected_records,
        matched_pairs=alignment.matched_pairs,
        field_strategies=params.field_matching,
    )
    overall_field_f1 = aggregate_field_f1(field_metrics)
    exact_match_rate = _compute_exact_match_rate(alignment.matched_pairs, params.field_matching)
    failure_reasons = _build_failure_reasons(
        record_metrics=record_metrics,
        overall_field_f1=overall_field_f1,
        thresholds=params.thresholds,
        execution_summary=execution_summary,
    )
    return ScenarioResult(
        record_metrics=record_metrics,
        field_metrics=field_metrics,
        overall_field_f1=overall_field_f1,
        exact_match_rate=exact_match_rate,
        passed=not failure_reasons,
        graph_status=_graph_status(execution_summary),
        failure_reasons=failure_reasons,
    )


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _compute_exact_match_rate(
    matched_pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    field_matching: dict[str, str],
) -> float:
    if not matched_pairs:
        return 0.0
    exact_matches = sum(
        1
        for actual_record, expected_record in matched_pairs
        if _records_match_exactly(actual_record, expected_record, field_matching)
    )
    return exact_matches / len(matched_pairs)


def _records_match_exactly(
    actual_record: dict[str, Any],
    expected_record: dict[str, Any],
    field_matching: dict[str, str],
) -> bool:
    for field_name, strategy in field_matching.items():
        if not field_match(
            actual_record.get(field_name), expected_record.get(field_name), strategy=strategy
        ):
            return False
    return True


def _build_failure_reasons(
    *,
    record_metrics: RecordMetrics,
    overall_field_f1: float,
    thresholds: dict[str, float | int],
    execution_summary: dict[str, Any] | None,
) -> list[str]:
    reasons: list[str] = []
    min_record_recall = float(thresholds.get("min_record_recall", 0.0))
    min_field_f1 = float(thresholds.get("min_field_f1", 0.0))
    max_steps = int(thresholds.get("max_steps", 0))
    if record_metrics.recall < min_record_recall:
        reasons.append(f"record_recall={record_metrics.recall:.3f} < {min_record_recall:.3f}")
    if overall_field_f1 < min_field_f1:
        reasons.append(f"field_f1={overall_field_f1:.3f} < {min_field_f1:.3f}")
    reasons.extend(_step_failure_reasons(max_steps=max_steps, execution_summary=execution_summary))
    return reasons


def _step_failure_reasons(
    *,
    max_steps: int,
    execution_summary: dict[str, Any] | None,
) -> list[str]:
    if max_steps <= 0:
        return []
    if execution_summary is None or "total_graph_steps" not in execution_summary:
        return [MISSING_STEPS_REASON]
    total_steps = int(execution_summary["total_graph_steps"])
    if total_steps > max_steps:
        return [f"total_graph_steps={total_steps} > {max_steps}"]
    return []


def _graph_status(execution_summary: dict[str, Any] | None) -> str:
    if execution_summary is None:
        return DEFAULT_GRAPH_STATUS
    return str(execution_summary.get("graph_status", DEFAULT_GRAPH_STATUS))
