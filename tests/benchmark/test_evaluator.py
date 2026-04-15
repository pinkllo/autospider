"""Tests for benchmark scenario evaluation."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest


def test_evaluate_scenario_full() -> None:
    """Evaluation combines record and field metrics into one result."""
    from tests.benchmark.evaluator import EvaluationParams, evaluate_scenario

    temp_dir = _make_temp_dir("evaluator_full")
    ground_truth_file = temp_dir / "gt.jsonl"
    actual_results_file = temp_dir / "actual.jsonl"
    _write_jsonl(
        ground_truth_file,
        [
            {"product_name": "Galaxy S25", "price": 9999.0, "brand": "Samsung"},
            {"product_name": "iPhone 16", "price": 8999.0, "brand": "Apple"},
            {"product_name": "Pixel 9", "price": 6999.0, "brand": "Google"},
        ],
    )
    _write_jsonl(
        actual_results_file,
        [
            {"product_name": "Galaxy S25", "price": 9999.0, "brand": "Samsung"},
            {"product_name": "iPhone 16", "price": 9000.0, "brand": "Apple"},
            {"product_name": "Unknown", "price": 1000.0, "brand": "NoName"},
        ],
    )

    result = evaluate_scenario(
        actual_file=actual_results_file,
        ground_truth_file=ground_truth_file,
        params=EvaluationParams(
            match_key="product_name",
            field_matching={
                "product_name": "exact",
                "price": "numeric_tolerance",
                "brand": "exact",
            },
            thresholds={"min_record_recall": 0.5, "min_field_f1": 0.5, "max_steps": 100},
        ),
    )

    assert result.record_metrics.matched == 2
    assert result.record_metrics.expected_total == 3
    assert result.field_metrics["product_name"].f1 == pytest.approx(2 / 3)
    assert result.field_metrics["brand"].f1 == pytest.approx(2 / 3)
    assert result.field_metrics["price"].correct == 1
    assert result.overall_field_f1 > 0


def test_evaluate_field_recall_counts_missing_expected_records() -> None:
    """Field recall drops when a ground-truth record is completely missing."""
    from tests.benchmark.evaluator import EvaluationParams, evaluate_scenario

    temp_dir = _make_temp_dir("evaluator_missing_record")
    ground_truth_file = temp_dir / "gt.jsonl"
    actual_results_file = temp_dir / "actual.jsonl"
    _write_jsonl(
        ground_truth_file,
        [
            {"product_name": "Galaxy S25", "brand": "Samsung"},
            {"product_name": "iPhone 16", "brand": "Apple"},
        ],
    )
    _write_jsonl(actual_results_file, [{"product_name": "Galaxy S25", "brand": "Samsung"}])

    result = evaluate_scenario(
        actual_file=actual_results_file,
        ground_truth_file=ground_truth_file,
        params=EvaluationParams(
            match_key="product_name",
            field_matching={"brand": "exact"},
            thresholds={"min_record_recall": 0.0, "min_field_f1": 0.0, "max_steps": 10},
        ),
        execution_summary={"graph_status": "completed", "total_graph_steps": 1},
    )

    assert result.field_metrics["brand"].precision == pytest.approx(1.0)
    assert result.field_metrics["brand"].recall == pytest.approx(0.5)


def test_evaluate_empty_actual_file() -> None:
    """Empty actual files yield zeroed metrics without crashing."""
    from tests.benchmark.evaluator import EvaluationParams, evaluate_scenario

    temp_dir = _make_temp_dir("evaluator_empty")
    ground_truth_file = temp_dir / "gt.jsonl"
    actual_results_file = temp_dir / "actual.jsonl"
    _write_jsonl(ground_truth_file, [{"product_name": "Galaxy S25"}])
    actual_results_file.write_text("", encoding="utf-8")

    result = evaluate_scenario(
        actual_file=actual_results_file,
        ground_truth_file=ground_truth_file,
        params=EvaluationParams(
            match_key="product_name",
            field_matching={"product_name": "exact"},
            thresholds={"min_record_recall": 0.5, "min_field_f1": 0.5, "max_steps": 100},
        ),
    )

    assert result.record_metrics.matched == 0
    assert result.record_metrics.recall == 0.0
    assert result.passed is False


def test_evaluate_missing_total_graph_steps_is_explicit_failure() -> None:
    """Missing total_graph_steps cannot silently satisfy max_steps."""
    from tests.benchmark.evaluator import EvaluationParams, evaluate_scenario

    temp_dir = _make_temp_dir("evaluator_missing_steps")
    ground_truth_file = temp_dir / "gt.jsonl"
    actual_results_file = temp_dir / "actual.jsonl"
    _write_jsonl(ground_truth_file, [{"product_name": "Galaxy S25"}])
    _write_jsonl(actual_results_file, [{"product_name": "Galaxy S25"}])

    result = evaluate_scenario(
        actual_file=actual_results_file,
        ground_truth_file=ground_truth_file,
        params=EvaluationParams(
            match_key="product_name",
            field_matching={"product_name": "exact"},
            thresholds={"min_record_recall": 0.0, "min_field_f1": 0.0, "max_steps": 10},
        ),
        execution_summary={"graph_status": "completed"},
    )

    assert result.passed is False
    assert any("total_graph_steps" in reason for reason in result.failure_reasons)


def test_evaluate_applies_threshold_failures() -> None:
    """Threshold violations are preserved as explicit failure reasons."""
    from tests.benchmark.evaluator import EvaluationParams, evaluate_scenario

    temp_dir = _make_temp_dir("evaluator_thresholds")
    ground_truth_file = temp_dir / "gt.jsonl"
    actual_results_file = temp_dir / "actual.jsonl"
    _write_jsonl(ground_truth_file, [{"product_name": "Galaxy S25", "price": 9999.0}])
    _write_jsonl(actual_results_file, [{"product_name": "Galaxy S25", "price": 9000.0}])

    result = evaluate_scenario(
        actual_file=actual_results_file,
        ground_truth_file=ground_truth_file,
        params=EvaluationParams(
            match_key="product_name",
            field_matching={"product_name": "exact", "price": "exact"},
            thresholds={"min_record_recall": 0.99, "min_field_f1": 0.99, "max_steps": 10},
        ),
        execution_summary={"graph_status": "partial_success", "total_graph_steps": 11},
    )

    assert result.passed is False
    assert result.graph_status == "partial_success"
    assert any("field_f1" in reason for reason in result.failure_reasons)
    assert any("total_graph_steps" in reason for reason in result.failure_reasons)


def test_evaluate_duplicate_actual_records_only_match_once() -> None:
    """Duplicate actual match keys stay visible as false positives."""
    from tests.benchmark.evaluator import EvaluationParams, evaluate_scenario

    temp_dir = _make_temp_dir("evaluator_duplicate_actual")
    ground_truth_file = temp_dir / "gt.jsonl"
    actual_results_file = temp_dir / "actual.jsonl"
    _write_jsonl(ground_truth_file, [{"product_name": "Galaxy S25"}, {"product_name": "iPhone 16"}])
    _write_jsonl(
        actual_results_file,
        [
            {"product_name": "Galaxy S25"},
            {"product_name": "Galaxy S25"},
            {"product_name": "iPhone 16"},
        ],
    )

    result = evaluate_scenario(
        actual_file=actual_results_file,
        ground_truth_file=ground_truth_file,
        params=EvaluationParams(
            match_key="product_name",
            field_matching={"product_name": "exact"},
            thresholds={"min_record_recall": 0.0, "min_field_f1": 0.0, "max_steps": 10},
        ),
        execution_summary={"graph_status": "completed", "total_graph_steps": 1},
    )

    assert result.record_metrics.matched == 2
    assert result.record_metrics.precision == pytest.approx(2 / 3)
    assert result.record_metrics.unmatched_actual == [{"product_name": "Galaxy S25"}]


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _make_temp_dir(name: str) -> Path:
    path = Path(".tmp") / "benchmark_tests" / name / uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    return path
