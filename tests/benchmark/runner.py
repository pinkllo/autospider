"""Benchmark runner orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import import_module
from pathlib import Path
from shutil import move
from typing import Any, Callable
from uuid import uuid4

from .evaluator import EvaluationParams, ScenarioResult, evaluate_scenario
from .scenarios.schema import ScenarioConfig, list_scenarios, load_scenario

RESULT_FILE_NAME = "merged_results.jsonl"


@dataclass(frozen=True)
class ScenarioRunResult:
    """Runner output for one benchmark scenario."""

    scenario_id: str
    actual_file: Path
    execution_summary: dict[str, Any]
    evaluation_result: ScenarioResult


class BenchmarkRunner:
    """Load scenarios, execute them, and evaluate produced results."""

    def __init__(
        self,
        *,
        scenarios_dir: Path,
        ground_truth_dir: Path,
        base_url: str,
        executor: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
        clean_output_dir: bool | None = None,
    ) -> None:
        self._scenarios_dir = scenarios_dir
        self._ground_truth_dir = ground_truth_dir
        self._base_url = base_url
        self._executor = executor or self._invoke_autospider
        self._clean_output_dir = (executor is None) if clean_output_dir is None else clean_output_dir

    def list_scenarios(self) -> list[str]:
        """List available benchmark scenarios."""
        return list_scenarios(self._scenarios_dir)

    def run_scenario(self, scenario_id: str) -> ScenarioRunResult:
        """Run one scenario via the injected executor and evaluate its output."""
        scenario = load_scenario(scenario_id, self._scenarios_dir)
        resolved_task = scenario.resolve_for_base_url(self._base_url)
        if self._clean_output_dir:
            self._prepare_output_dir(scenario.scenario.id, resolved_task.cli_overrides)
        execution_summary = self._executor(resolved_task.request, resolved_task.cli_overrides)
        actual_file = self._find_result_file(resolved_task.cli_overrides)
        ground_truth_file = self._resolve_ground_truth_file(scenario)
        evaluation_result = evaluate_scenario(
            actual_file=actual_file,
            ground_truth_file=ground_truth_file,
            params=_build_evaluation_params(scenario),
            execution_summary=execution_summary,
        )
        return ScenarioRunResult(
            scenario_id=scenario.scenario.id,
            actual_file=actual_file,
            execution_summary=execution_summary,
            evaluation_result=evaluation_result,
        )

    def run_all(self) -> dict[str, ScenarioRunResult]:
        """Run all configured scenarios."""
        return {
            scenario_id: self.run_scenario(scenario_id) for scenario_id in self.list_scenarios()
        }

    def _invoke_autospider(self, request: str, cli_overrides: dict[str, Any]) -> dict[str, Any]:
        executor = _load_benchmark_executor()
        result = dict(executor(request, dict(cli_overrides)))
        return _normalize_execution_summary(result)

    def _prepare_output_dir(self, scenario_id: str, cli_overrides: dict[str, Any]) -> None:
        output_dir = _resolve_output_dir(cli_overrides)
        if output_dir is None:
            return
        _archive_existing_output(output_dir, scenario_id=scenario_id)
        output_dir.mkdir(parents=True, exist_ok=True)

    def _find_result_file(self, cli_overrides: dict[str, Any]) -> Path:
        output_dir = _resolve_output_dir(cli_overrides)
        if output_dir is None:
            raise KeyError("Scenario task.cli_overrides.output_dir is required.")
        result_file = output_dir / RESULT_FILE_NAME
        if not result_file.exists():
            raise FileNotFoundError(f"Benchmark result file not found: {result_file}")
        return result_file

    def _resolve_ground_truth_file(self, scenario: ScenarioConfig) -> Path:
        ground_truth_path = Path(scenario.ground_truth.file)
        if ground_truth_path.parts and ground_truth_path.parts[0] == "ground_truth":
            ground_truth_path = Path(*ground_truth_path.parts[1:])
        resolved = self._ground_truth_dir / ground_truth_path
        if not resolved.exists():
            raise FileNotFoundError(f"Ground truth file not found: {resolved}")
        return resolved


def _build_evaluation_params(scenario: ScenarioConfig) -> EvaluationParams:
    return EvaluationParams(
        match_key=scenario.evaluation.match_key,
        field_matching=dict(scenario.evaluation.field_matching),
        thresholds=scenario.evaluation.thresholds.model_dump(),
    )


def _load_benchmark_executor() -> Callable[[str, dict[str, Any]], dict[str, Any]]:
    runtime_module = import_module("autospider.composition.use_cases.benchmark_runtime")
    executor = getattr(runtime_module, "execute_benchmark_graph", None)
    if not callable(executor):
        raise RuntimeError("autospider.composition.use_cases.benchmark_runtime is unavailable.")
    return executor


def _normalize_execution_summary(summary: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(summary)
    status = normalized.get("status")
    if "graph_status" not in normalized and status is not None:
        normalized["graph_status"] = status
    return normalized


def _resolve_output_dir(cli_overrides: dict[str, Any]) -> Path | None:
    output_dir = str(cli_overrides.get("output_dir") or "").strip()
    if not output_dir:
        return None
    return Path(output_dir)


def _archive_existing_output(output_dir: Path, *, scenario_id: str) -> None:
    if not output_dir.exists():
        return
    archive_target = _benchmark_trash_dir() / scenario_id / _archive_name(output_dir.name)
    archive_target.parent.mkdir(parents=True, exist_ok=True)
    move(str(output_dir), str(archive_target))


def _benchmark_trash_dir() -> Path:
    return Path(".task_trash") / "benchmark"


def _archive_name(output_name: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{timestamp}-{uuid4().hex[:8]}-{output_name}"
