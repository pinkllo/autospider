"""Benchmark runner orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, Callable

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
    ) -> None:
        self._scenarios_dir = scenarios_dir
        self._ground_truth_dir = ground_truth_dir
        self._base_url = base_url
        self._executor = executor or self._invoke_autospider

    def list_scenarios(self) -> list[str]:
        """List available benchmark scenarios."""
        return list_scenarios(self._scenarios_dir)

    def run_scenario(self, scenario_id: str) -> ScenarioRunResult:
        """Run one scenario via the injected executor and evaluate its output."""
        scenario = load_scenario(scenario_id, self._scenarios_dir)
        resolved_task = scenario.resolve_for_base_url(self._base_url)
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
        return {scenario_id: self.run_scenario(scenario_id) for scenario_id in self.list_scenarios()}

    def _invoke_autospider(self, request: str, cli_overrides: dict[str, Any]) -> dict[str, Any]:
        invoke_graph = _load_cli_invoke_graph()
        cli_args = {"request": request, **dict(cli_overrides)}
        result = dict(invoke_graph("chat_pipeline", cli_args, thread_id=""))
        return _normalize_execution_summary(result)

    def _find_result_file(self, cli_overrides: dict[str, Any]) -> Path:
        output_dir = cli_overrides.get("output_dir")
        if not output_dir:
            raise KeyError("Scenario task.cli_overrides.output_dir is required.")
        result_file = Path(str(output_dir)) / RESULT_FILE_NAME
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


def _load_cli_invoke_graph() -> Callable[[str, dict[str, Any]], dict[str, Any]]:
    cli_module = import_module("autospider.cli")
    invoke_graph = getattr(cli_module, "_invoke_graph", None)
    if not callable(invoke_graph):
        raise RuntimeError("autospider.cli._invoke_graph is unavailable.")
    return invoke_graph


def _normalize_execution_summary(summary: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(summary)
    status = normalized.get("status")
    if "graph_status" not in normalized and status is not None:
        normalized["graph_status"] = status
    return normalized
