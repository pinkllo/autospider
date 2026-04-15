"""Tests for benchmark report generation."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from tests.benchmark.metrics import FieldMetrics, RecordMetrics


def test_generate_json_report_preserves_missing_sections() -> None:
    """Reporter keeps missing efficiency or stability fields absent."""
    from tests.benchmark.reporter import generate_json_report

    output_path = _make_temp_dir("report_json") / "report.json"
    generate_json_report(
        {"products": _scenario_result(passed=True)},
        output_path=output_path,
        git_commit="abc1234",
        efficiency_data={"products": {"total_graph_steps": 23}},
        stability_data={},
    )

    report = json.loads(output_path.read_text("utf-8"))

    assert report["git_commit"] == "abc1234"
    assert report["scenarios"]["products"]["status"] == "pass"
    assert report["scenarios"]["products"]["efficiency"]["total_graph_steps"] == 23
    assert "stability" not in report["scenarios"]["products"]


def test_generate_markdown_report() -> None:
    """Markdown output includes scenario details and compare content."""
    from tests.benchmark.reporter import generate_markdown_report

    output_path = _make_temp_dir("report_markdown") / "report.md"
    generate_markdown_report(
        {"products": _scenario_result(passed=False)},
        output_path=output_path,
        compare_results={
            "products": {
                "status": {"before": "fail", "after": "pass"},
                "record_f1": {"before": 0.7, "after": 0.8},
            }
        },
    )

    content = output_path.read_text("utf-8")

    assert "products" in content
    assert "record_f1" in content
    assert "graph_status" in content
    assert "failure_reasons" in content
    assert "Compare" in content


def test_compare_reports() -> None:
    """JSON reports can be compared scenario by scenario."""
    from tests.benchmark.reporter import compare_reports, generate_json_report

    temp_dir = _make_temp_dir("report_compare")
    old_path = temp_dir / "old.json"
    new_path = temp_dir / "new.json"
    generate_json_report(
        {"products": _scenario_result(passed=False)},
        output_path=old_path,
        git_commit="old123",
    )
    generate_json_report(
        {"products": _scenario_result(passed=True)},
        output_path=new_path,
        git_commit="new456",
    )

    diff = compare_reports(old_path, new_path)

    assert "products" in diff
    assert diff["products"]["status"]["before"] == "fail"
    assert diff["products"]["status"]["after"] == "pass"


def test_compare_reports_requires_existing_history() -> None:
    """Missing historical report is an explicit error."""
    from tests.benchmark.reporter import compare_reports

    temp_dir = _make_temp_dir("report_missing")

    with pytest.raises(FileNotFoundError):
        compare_reports(temp_dir / "old.json", temp_dir / "new.json")


def _scenario_result(*, passed: bool) -> object:
    from tests.benchmark.evaluator import ScenarioResult

    return ScenarioResult(
        record_metrics=RecordMetrics(
            matched=12,
            actual_total=14,
            expected_total=15,
            precision=12 / 14,
            recall=12 / 15,
            f1=0.857,
            unmatched_actual=[{"name": "X"}],
            unmatched_expected=[{"name": "Y"}, {"name": "Z"}],
        ),
        field_metrics={
            "product_name": FieldMetrics(
                field_name="product_name",
                correct=12,
                total=12,
                precision=1.0,
                recall=1.0,
                f1=1.0,
            ),
            "price": FieldMetrics(
                field_name="price",
                correct=10,
                total=12,
                precision=0.833,
                recall=0.833,
                f1=0.833,
            ),
        },
        overall_field_f1=0.916,
        exact_match_rate=0.75,
        passed=passed,
        graph_status="completed" if passed else "partial_success",
        failure_reasons=[] if passed else ["record_recall=0.800 < 0.900"],
    )


def _make_temp_dir(name: str) -> Path:
    path = Path(".tmp") / "benchmark_tests" / name / uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    return path
