"""Pytest benchmark entrypoint for all benchmark scenarios."""

from __future__ import annotations

from pathlib import Path

import pytest

SCENARIOS_DIR = Path(__file__).resolve().parent / "scenarios"
SCENARIO_IDS = sorted(path.stem for path in SCENARIOS_DIR.glob("*.yaml"))
pytestmark = pytest.mark.benchmark


def test_benchmark_fixtures_exist(benchmark_base_url: str, benchmark_runner: object) -> None:
    """Core benchmark fixtures are available to scenario tests."""
    assert benchmark_base_url.startswith("http://127.0.0.1:")
    assert benchmark_runner is not None


@pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
def test_benchmark_scenario_entrypoint(
    scenario_id: str,
    benchmark_runner: object,
) -> None:
    """Each benchmark scenario has a single parameterized pytest entrypoint."""
    from autospider.composition.use_cases.benchmark_runtime import BenchmarkRuntimeUnavailable
    from tests.benchmark.runner import ScenarioRunResult
    from tests.benchmark.scenarios.schema import load_scenario

    config = load_scenario(scenario_id)
    assert "{base_url}" in config.task.request

    runner = benchmark_runner
    if not hasattr(runner, "run_scenario"):
        pytest.fail("benchmark_runner fixture must provide run_scenario().")

    try:
        result = runner.run_scenario(scenario_id)
    except ImportError as exc:
        pytest.skip(f"benchmark runtime unavailable: {exc}")
    except BenchmarkRuntimeUnavailable as exc:
        pytest.skip(f"benchmark runtime unavailable: {exc}")

    assert isinstance(result, ScenarioRunResult)
    thresholds = config.evaluation.thresholds
    assert result.evaluation_result.record_metrics.recall >= thresholds.min_record_recall
    assert result.evaluation_result.overall_field_f1 >= thresholds.min_field_f1
    assert result.execution_summary["total_graph_steps"] <= thresholds.max_steps
