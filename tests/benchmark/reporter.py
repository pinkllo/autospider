"""Report generation helpers for benchmark runs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .evaluator import ScenarioResult


def generate_json_report(
    results: dict[str, ScenarioResult],
    *,
    output_path: Path,
    git_commit: str,
    efficiency_data: dict[str, dict[str, Any]] | None = None,
    stability_data: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Write a machine-readable benchmark report to JSON."""
    report = {
        "run_id": _utc_now_iso(),
        "git_commit": git_commit,
        "scenarios": _build_scenarios_payload(results, efficiency_data, stability_data),
        "overall": _build_overall_payload(results),
    }
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def generate_markdown_report(
    results: dict[str, ScenarioResult],
    *,
    output_path: Path,
    compare_results: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Write a human-readable benchmark report to Markdown."""
    lines = [
        "# Benchmark Report",
        "",
        "| scenario | status | record_f1 | field_f1 |",
        "| --- | --- | ---: | ---: |",
    ]
    for scenario_id, result in sorted(results.items()):
        lines.append(
            f"| {scenario_id} | {_scenario_status(result)} | "
            f"{result.record_metrics.f1:.3f} | {result.overall_field_f1:.3f} |"
        )
    for scenario_id, result in sorted(results.items()):
        lines.extend(_scenario_detail_lines(scenario_id, result))
    if compare_results:
        lines.extend(_compare_lines(compare_results))
    content = "\n".join(lines) + "\n"
    output_path.write_text(content, encoding="utf-8")
    return content


def compare_reports(old_report_path: Path, new_report_path: Path) -> dict[str, Any]:
    """Compare two JSON benchmark reports."""
    old_report = _load_report(old_report_path)
    new_report = _load_report(new_report_path)
    scenario_ids = set(old_report["scenarios"]) | set(new_report["scenarios"])
    return {
        scenario_id: _compare_scenario_payload(
            old_report["scenarios"].get(scenario_id, {}),
            new_report["scenarios"].get(scenario_id, {}),
        )
        for scenario_id in sorted(scenario_ids)
    }


def _build_scenarios_payload(
    results: dict[str, ScenarioResult],
    efficiency_data: dict[str, dict[str, Any]] | None,
    stability_data: dict[str, dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    payload: dict[str, dict[str, Any]] = {}
    for scenario_id, result in sorted(results.items()):
        payload[scenario_id] = _build_single_scenario_payload(
            result=result,
            efficiency=efficiency_data.get(scenario_id) if efficiency_data else None,
            stability=stability_data.get(scenario_id) if stability_data else None,
        )
    return payload


def _build_single_scenario_payload(
    *,
    result: ScenarioResult,
    efficiency: dict[str, Any] | None,
    stability: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = {
        "status": _scenario_status(result),
        "graph_status": result.graph_status,
        "accuracy": {
            "record_precision": result.record_metrics.precision,
            "record_recall": result.record_metrics.recall,
            "record_f1": result.record_metrics.f1,
            "field_f1": result.overall_field_f1,
            "exact_match_rate": result.exact_match_rate,
        },
        "failure_reasons": result.failure_reasons,
    }
    if efficiency:
        payload["efficiency"] = efficiency
    if stability:
        payload["stability"] = stability
    return payload


def _build_overall_payload(results: dict[str, ScenarioResult]) -> dict[str, Any]:
    passed_count = sum(1 for result in results.values() if result.passed)
    total_count = len(results)
    return {
        "scenarios_passed": passed_count,
        "scenarios_failed": total_count - passed_count,
        "avg_record_f1": _average(result.record_metrics.f1 for result in results.values()),
        "avg_field_f1": _average(result.overall_field_f1 for result in results.values()),
    }


def _compare_scenario_payload(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": {"before": before.get("status"), "after": after.get("status")},
        "record_f1": {
            "before": before.get("accuracy", {}).get("record_f1"),
            "after": after.get("accuracy", {}).get("record_f1"),
        },
        "field_f1": {
            "before": before.get("accuracy", {}).get("field_f1"),
            "after": after.get("accuracy", {}).get("field_f1"),
        },
    }


def _load_report(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Benchmark report not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _scenario_status(result: ScenarioResult) -> str:
    return "pass" if result.passed else "fail"


def _average(values: Any) -> float:
    numbers = list(values)
    if not numbers:
        return 0.0
    return sum(numbers) / len(numbers)


def _scenario_detail_lines(scenario_id: str, result: ScenarioResult) -> list[str]:
    return [
        "",
        f"## {scenario_id}",
        f"- graph_status: {result.graph_status}",
        f"- record_f1: {result.record_metrics.f1:.3f}",
        f"- field_f1: {result.overall_field_f1:.3f}",
        f"- exact_match_rate: {result.exact_match_rate:.3f}",
        f"- failure_reasons: {result.failure_reasons or []}",
    ]


def _compare_lines(compare_results: dict[str, dict[str, Any]]) -> list[str]:
    lines = ["", "## Compare"]
    for scenario_id, payload in sorted(compare_results.items()):
        lines.append(f"- {scenario_id}: {json.dumps(payload, ensure_ascii=False)}")
    return lines
