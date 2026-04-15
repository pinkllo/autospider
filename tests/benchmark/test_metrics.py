"""Tests for benchmark metric calculations."""

from __future__ import annotations

import pytest


def test_exact_match_strategy() -> None:
    """Exact matching trims whitespace but stays case-sensitive."""
    from tests.benchmark.metrics import field_match

    assert field_match("  Apple  ", "Apple", strategy="exact") is True
    assert field_match("Apple", "apple", strategy="exact") is False


def test_numeric_tolerance_strategy() -> None:
    """Numeric tolerance compares parsed numeric values."""
    from tests.benchmark.metrics import field_match

    assert field_match("99.995", "99.99", strategy="numeric_tolerance") is True
    assert field_match("100.05", "99.99", strategy="numeric_tolerance") is False


def test_numeric_tolerance_rejects_non_numeric_values() -> None:
    """Parse failures should surface instead of silently downgrading."""
    from tests.benchmark.metrics import field_match

    with pytest.raises(ValueError):
        field_match("not-a-number", "99.99", strategy="numeric_tolerance")


def test_fuzzy_and_contains_match() -> None:
    """Fuzzy and contains strategies work for text fields."""
    from tests.benchmark.metrics import field_match

    assert field_match(
        "6.9英寸 AMOLED, 骁龙8 Gen4",
        "6.9英寸 AMOLED, 骁龙8 Gen4, 12GB RAM",
        strategy="fuzzy",
    )
    assert field_match("包含关键词的长文本", "关键词", strategy="contains")


def test_unknown_strategy_raises_error() -> None:
    """Unknown strategy names are explicit errors."""
    from tests.benchmark.metrics import field_match

    with pytest.raises(ValueError):
        field_match("A", "A", strategy="not-supported")


def test_precision_recall_f1() -> None:
    """Precision, recall, and F1 are computed consistently."""
    from tests.benchmark.metrics import precision_recall_f1

    precision, recall, f1 = precision_recall_f1(tp=8, fp=2, fn=2)

    assert precision == pytest.approx(0.8)
    assert recall == pytest.approx(0.8)
    assert f1 == pytest.approx(0.8)


def test_compute_record_metrics() -> None:
    """Record metrics align actual and expected rows by match key."""
    from tests.benchmark.metrics import compute_record_metrics

    actual = [
        {"name": "A", "price": "100"},
        {"name": "B", "price": "200"},
        {"name": "C", "price": "999"},
    ]
    expected = [
        {"name": "A", "price": "100"},
        {"name": "B", "price": "200"},
        {"name": "D", "price": "400"},
    ]

    metrics = compute_record_metrics(actual=actual, expected=expected, match_key="name")

    assert metrics.matched == 2
    assert metrics.actual_total == 3
    assert metrics.expected_total == 3
    assert metrics.precision == pytest.approx(2 / 3)
    assert metrics.recall == pytest.approx(2 / 3)


def test_compute_record_metrics_treats_duplicate_actual_keys_as_false_positives() -> None:
    """Duplicate actual match keys are extra false positives, not extra matches."""
    from tests.benchmark.metrics import compute_record_metrics

    metrics = compute_record_metrics(
        actual=[{"name": "A"}, {"name": "A"}, {"name": "B"}],
        expected=[{"name": "A"}, {"name": "B"}],
        match_key="name",
    )

    assert metrics.matched == 2
    assert metrics.precision == pytest.approx(2 / 3)
    assert metrics.recall == pytest.approx(1.0)
    assert metrics.unmatched_actual == [{"name": "A"}]


def test_compute_field_metrics_and_aggregate() -> None:
    """Field-level metrics are computed per field and aggregated."""
    from tests.benchmark.metrics import aggregate_field_f1, compute_field_metrics

    matched_pairs = [
        ({"name": "A", "price": "100"}, {"name": "A", "price": "100"}),
        ({"name": "B", "price": "999"}, {"name": "B", "price": "200"}),
    ]

    field_results = compute_field_metrics(
        actual_records=[
            {"name": "A", "price": "100"},
            {"name": "B", "price": "999"},
        ],
        expected_records=[
            {"name": "A", "price": "100"},
            {"name": "B", "price": "200"},
            {"name": "C", "price": "300"},
        ],
        matched_pairs=matched_pairs,
        field_strategies={"name": "exact", "price": "exact"},
    )

    assert field_results["name"].f1 == pytest.approx(0.8)
    assert field_results["price"].precision == pytest.approx(0.5)
    assert field_results["name"].recall == pytest.approx(2 / 3)
    assert field_results["price"].recall == pytest.approx(1 / 3)
    assert field_results["price"].f1 == pytest.approx(0.4)
    assert aggregate_field_f1(field_results) == pytest.approx(0.6)
