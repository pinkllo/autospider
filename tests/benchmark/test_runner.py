"""Tests for benchmark runner orchestration."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest


def test_runner_run_scenario_with_injected_executor() -> None:
    """Runner loads scenario config, executes, and evaluates output."""
    from tests.benchmark.runner import BenchmarkRunner, ScenarioRunResult

    temp_dir = _make_temp_dir("runner_success")
    scenarios_dir = temp_dir / "scenarios"
    ground_truth_dir = temp_dir / "ground_truth"
    output_dir = temp_dir / "output"
    scenarios_dir.mkdir()
    ground_truth_dir.mkdir()
    output_dir.mkdir()
    _write_scenario_yaml(scenarios_dir / "test_run.yaml", output_dir)
    _write_jsonl(ground_truth_dir / "test_run.jsonl", [{"name": "A"}, {"name": "B"}])
    _write_jsonl(output_dir / "merged_results.jsonl", [{"name": "A"}, {"name": "B"}])

    runner = BenchmarkRunner(
        scenarios_dir=scenarios_dir,
        ground_truth_dir=ground_truth_dir,
        base_url="http://localhost:9999",
        executor=lambda request, overrides: {
            "graph_status": "partial_success",
            "total_graph_steps": 12,
            "request": request,
            "overrides": overrides,
        },
    )

    result = runner.run_scenario("test_run")

    assert isinstance(result, ScenarioRunResult)
    assert result.evaluation_result.passed is True
    assert result.evaluation_result.graph_status == "partial_success"
    assert result.execution_summary["graph_status"] == "partial_success"
    assert result.actual_file.name == "merged_results.jsonl"


def test_runner_list_scenarios() -> None:
    """Runner lists scenario ids from the scenario directory."""
    from tests.benchmark.runner import BenchmarkRunner

    temp_dir = _make_temp_dir("runner_list")
    scenarios_dir = temp_dir / "scenarios"
    scenarios_dir.mkdir()
    _write_scenario_yaml(scenarios_dir / "b.yaml", temp_dir / "output_b")
    _write_scenario_yaml(scenarios_dir / "a.yaml", temp_dir / "output_a", scenario_id="a")

    runner = BenchmarkRunner(
        scenarios_dir=scenarios_dir,
        ground_truth_dir=temp_dir,
        base_url="http://localhost:9999",
    )

    assert runner.list_scenarios() == ["a", "test_run"]


def test_runner_raises_when_result_file_missing() -> None:
    """Missing result files are surfaced explicitly."""
    from tests.benchmark.runner import BenchmarkRunner

    temp_dir = _make_temp_dir("runner_missing")
    scenarios_dir = temp_dir / "scenarios"
    ground_truth_dir = temp_dir / "ground_truth"
    output_dir = temp_dir / "output"
    scenarios_dir.mkdir()
    ground_truth_dir.mkdir()
    output_dir.mkdir()
    _write_scenario_yaml(scenarios_dir / "test_run.yaml", output_dir)
    _write_jsonl(ground_truth_dir / "test_run.jsonl", [{"name": "A"}])

    runner = BenchmarkRunner(
        scenarios_dir=scenarios_dir,
        ground_truth_dir=ground_truth_dir,
        base_url="http://localhost:9999",
        executor=lambda request, overrides: {"graph_status": "completed"},
    )

    with pytest.raises(FileNotFoundError):
        runner.run_scenario("test_run")


def test_runner_default_executor_uses_cli_entrypoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default executor delegates to the repository CLI graph entrypoint."""
    from tests.benchmark import runner as runner_module
    from tests.benchmark.runner import BenchmarkRunner

    captured: dict[str, object] = {}
    temp_dir = _make_temp_dir("runner_default_exec")
    scenarios_dir = temp_dir / "scenarios"
    ground_truth_dir = temp_dir / "ground_truth"
    output_dir = temp_dir / "output"
    scenarios_dir.mkdir()
    ground_truth_dir.mkdir()
    output_dir.mkdir()
    _write_scenario_yaml(scenarios_dir / "test_run.yaml", output_dir)
    _write_jsonl(ground_truth_dir / "test_run.jsonl", [{"name": "A"}])
    _write_jsonl(output_dir / "merged_results.jsonl", [{"name": "A"}])

    def fake_invoke_graph(
        entry_mode: str,
        cli_args: dict[str, object],
        *,
        thread_id: str = "",
    ) -> dict[str, object]:
        captured["entry_mode"] = entry_mode
        captured["cli_args"] = dict(cli_args)
        captured["thread_id"] = thread_id
        return {"status": "completed", "total_graph_steps": 7}

    monkeypatch.setattr(runner_module, "_load_cli_invoke_graph", lambda: fake_invoke_graph)
    runner = BenchmarkRunner(
        scenarios_dir=scenarios_dir,
        ground_truth_dir=ground_truth_dir,
        base_url="http://localhost:9999",
    )

    result = runner.run_scenario("test_run")

    assert result.execution_summary["graph_status"] == "completed"
    assert result.evaluation_result.graph_status == "completed"
    assert captured["entry_mode"] == "chat_pipeline"
    assert captured["thread_id"] == ""
    assert captured["cli_args"]["request"] == "采集 http://localhost:9999/test/"
    assert captured["cli_args"]["output_dir"] == output_dir.as_posix()


def _write_scenario_yaml(
    path: Path,
    output_dir: Path,
    *,
    scenario_id: str = "test_run",
) -> None:
    path.write_text(
        f"""
scenario:
  id: {scenario_id}
  name: Test
  description: Test runner
task:
  request: "采集 {{base_url}}/test/"
  cli_overrides:
    output_dir: "{output_dir.as_posix()}"
ground_truth:
  file: "ground_truth/{scenario_id}.jsonl"
  record_count: 2
  fields:
    - name: "name"
      type: "text"
evaluation:
  match_key: "name"
  field_matching:
    name: exact
  thresholds:
    min_record_recall: 0.5
    min_field_f1: 0.5
    max_steps: 100
""".strip(),
        encoding="utf-8",
    )


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _make_temp_dir(name: str) -> Path:
    path = Path(".tmp") / "benchmark_tests" / name / uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    return path
