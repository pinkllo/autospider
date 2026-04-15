"""Metric helpers for benchmark evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

FUZZY_THRESHOLD = 0.85
NUMERIC_TOLERANCE = 0.01
ZERO_DIVISION_VALUE = 0.0


@dataclass(frozen=True)
class RecordMetrics:
    """Record-level alignment metrics."""

    matched: int
    actual_total: int
    expected_total: int
    precision: float
    recall: float
    f1: float
    unmatched_actual: list[dict[str, Any]]
    unmatched_expected: list[dict[str, Any]]


@dataclass(frozen=True)
class FieldMetrics:
    """Field-level comparison metrics."""

    field_name: str
    correct: int
    total: int
    precision: float
    recall: float
    f1: float
    expected_total: int = 0

    @property
    def actual_total(self) -> int:
        """Compatibility alias for older tests and callers."""
        return self.total


@dataclass(frozen=True)
class RecordAlignment:
    """Unique-key alignment between actual and expected records."""

    matched_pairs: list[tuple[dict[str, Any], dict[str, Any]]]
    unmatched_actual: list[dict[str, Any]]
    unmatched_expected: list[dict[str, Any]]


def field_match(
    actual_value: Any,
    expected_value: Any,
    *,
    strategy: str,
    numeric_tolerance: float = NUMERIC_TOLERANCE,
    fuzzy_threshold: float = FUZZY_THRESHOLD,
) -> bool:
    """Compare two field values using a named strategy."""
    actual_text = _normalize_value(actual_value)
    expected_text = _normalize_value(expected_value)
    if strategy == "exact":
        return actual_text == expected_text
    if strategy == "numeric_tolerance":
        return _numeric_match(actual_text, expected_text, numeric_tolerance)
    if strategy == "fuzzy":
        return _fuzzy_match(actual_text, expected_text, fuzzy_threshold)
    if strategy == "contains":
        return expected_text in actual_text
    raise ValueError(f"Unsupported field matching strategy: {strategy}")


def precision_recall_f1(*, tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    """Compute precision, recall, and F1 from confusion counts."""
    precision = _safe_divide(tp, tp + fp)
    recall = _safe_divide(tp, tp + fn)
    f1 = _safe_divide(2 * precision * recall, precision + recall)
    return precision, recall, f1


def align_records(
    *,
    actual: list[dict[str, Any]],
    expected: list[dict[str, Any]],
    match_key: str,
) -> RecordAlignment:
    """Align actual and expected records by unique match key."""
    expected_by_key = _index_records(expected, match_key)
    matched_keys: set[str] = set()
    matched_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    unmatched_actual: list[dict[str, Any]] = []
    for record in actual:
        key = _record_key(record, match_key)
        if not key or key not in expected_by_key or key in matched_keys:
            unmatched_actual.append(record)
            continue
        matched_keys.add(key)
        matched_pairs.append((record, expected_by_key[key]))
    unmatched_expected = [
        record for key, record in expected_by_key.items() if key not in matched_keys
    ]
    return RecordAlignment(
        matched_pairs=matched_pairs,
        unmatched_actual=unmatched_actual,
        unmatched_expected=unmatched_expected,
    )


def compute_record_metrics(
    *,
    actual: list[dict[str, Any]],
    expected: list[dict[str, Any]],
    match_key: str,
) -> RecordMetrics:
    """Compute record-level metrics from aligned match keys."""
    alignment = align_records(actual=actual, expected=expected, match_key=match_key)
    matched = len(alignment.matched_pairs)
    precision, recall, f1 = precision_recall_f1(
        tp=matched,
        fp=len(alignment.unmatched_actual),
        fn=len(alignment.unmatched_expected),
    )
    return RecordMetrics(
        matched=matched,
        actual_total=len(actual),
        expected_total=len(expected),
        precision=precision,
        recall=recall,
        f1=f1,
        unmatched_actual=alignment.unmatched_actual,
        unmatched_expected=alignment.unmatched_expected,
    )


def compute_field_metrics(
    *,
    actual_records: list[dict[str, Any]],
    expected_records: list[dict[str, Any]],
    matched_pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    field_strategies: dict[str, str],
) -> dict[str, FieldMetrics]:
    """Compute field-level metrics for configured fields."""
    metrics: dict[str, FieldMetrics] = {}
    for field_name, strategy in field_strategies.items():
        metrics[field_name] = _compute_single_field_metrics(
            actual_records=actual_records,
            expected_records=expected_records,
            matched_pairs=matched_pairs,
            field_name=field_name,
            strategy=strategy,
        )
    return metrics


def aggregate_field_f1(field_metrics: dict[str, FieldMetrics]) -> float:
    """Average field F1 values across all evaluated fields."""
    if not field_metrics:
        return ZERO_DIVISION_VALUE
    return sum(metric.f1 for metric in field_metrics.values()) / len(field_metrics)


def _compute_single_field_metrics(
    *,
    actual_records: list[dict[str, Any]],
    expected_records: list[dict[str, Any]],
    matched_pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    field_name: str,
    strategy: str,
) -> FieldMetrics:
    actual_total = _count_present_field_values(actual_records, field_name)
    expected_total = _count_present_field_values(expected_records, field_name)
    correct = _count_correct_field_values(matched_pairs, field_name, strategy)
    precision, recall, f1 = precision_recall_f1(
        tp=correct,
        fp=actual_total - correct,
        fn=expected_total - correct,
    )
    return FieldMetrics(
        field_name=field_name,
        correct=correct,
        total=actual_total,
        expected_total=expected_total,
        precision=precision,
        recall=recall,
        f1=f1,
    )


def _count_present_field_values(records: list[dict[str, Any]], field_name: str) -> int:
    return sum(1 for record in records if _has_field_value(record, field_name))


def _count_correct_field_values(
    matched_pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    field_name: str,
    strategy: str,
) -> int:
    return sum(
        1
        for actual_record, expected_record in matched_pairs
        if _is_correct_field_value(actual_record, expected_record, field_name, strategy)
    )


def _is_correct_field_value(
    actual_record: dict[str, Any],
    expected_record: dict[str, Any],
    field_name: str,
    strategy: str,
) -> bool:
    if not _has_field_value(actual_record, field_name):
        return False
    if not _has_field_value(expected_record, field_name):
        return False
    return field_match(actual_record[field_name], expected_record[field_name], strategy=strategy)


def _has_field_value(record: dict[str, Any], field_name: str) -> bool:
    value = record.get(field_name)
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _index_records(records: list[dict[str, Any]], match_key: str) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for record in records:
        key = _record_key(record, match_key)
        if key and key not in indexed:
            indexed[key] = record
    return indexed


def _record_key(record: dict[str, Any], match_key: str) -> str:
    return _normalize_value(record.get(match_key))


def _normalize_value(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _numeric_match(actual_text: str, expected_text: str, tolerance: float) -> bool:
    actual_number = float(actual_text)
    expected_number = float(expected_text)
    return abs(actual_number - expected_number) <= tolerance


def _fuzzy_match(actual_text: str, expected_text: str, fuzzy_threshold: float) -> bool:
    if actual_text in expected_text or expected_text in actual_text:
        return True
    return SequenceMatcher(None, actual_text, expected_text).ratio() >= fuzzy_threshold


def _safe_divide(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return ZERO_DIVISION_VALUE
    return numerator / denominator
