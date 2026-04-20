from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from rich.panel import Panel

from autospider.composition.use_cases.run_benchmark import BenchmarkReportService

from ._rendering import console
from ._runtime import cli_runtime

_SERVICE = BenchmarkReportService()


def _benchmark_reports_dir() -> Path:
    return _SERVICE.reports_dir()


def _benchmark_json_reports() -> list[Path]:
    return _SERVICE.json_reports()


def _latest_benchmark_report_path() -> Path:
    return _SERVICE.latest_report_path()


def _last_two_benchmark_reports() -> tuple[Path, Path]:
    return _SERVICE.last_two_report_paths()


def _benchmark_git_commit() -> str:
    return _SERVICE.benchmark_git_commit()


def _load_benchmark_runner() -> type:
    return _SERVICE.load_runner_class()


def _load_benchmark_reporter() -> Any:
    return _SERVICE.load_reporter()


def _benchmark_paths():
    return _SERVICE.benchmark_paths()


def _build_benchmark_runner(base_url: str) -> Any:
    paths = _benchmark_paths()
    return _load_benchmark_runner()(
        scenarios_dir=paths.scenarios,
        ground_truth_dir=paths.ground_truth,
        base_url=base_url,
    )


def _list_benchmark_scenarios() -> list[str]:
    return _SERVICE.list_scenarios()


def _render_latest_benchmark_report() -> str:
    report_path = _latest_benchmark_report_path()
    markdown_path = report_path.with_suffix(".md")
    output_path = markdown_path if markdown_path.exists() else report_path
    return output_path.read_text(encoding="utf-8")


def _compare_latest_benchmark_reports() -> dict[str, Any]:
    previous_path, latest_path = _last_two_benchmark_reports()
    return _load_benchmark_reporter().compare_reports(previous_path, latest_path)


def _compare_new_benchmark_report(new_report_path: Path) -> dict[str, Any]:
    existing_reports = [path for path in _benchmark_json_reports() if path != new_report_path]
    if not existing_reports:
        raise FileNotFoundError(
            f"Need at least one previous benchmark report in {_benchmark_reports_dir()}"
        )
    return _load_benchmark_reporter().compare_reports(existing_reports[-1], new_report_path)


def _run_benchmark_and_write_reports(selected_scenarios: list[str]) -> tuple[Path, Path]:
    from tests.benchmark.mock_site.server import MockSiteServer

    paths = _benchmark_paths()
    _benchmark_reports_dir().mkdir(parents=True, exist_ok=True)
    server = MockSiteServer(root_dir=paths.mock_site, port=0)
    server.start()
    try:
        runner = _build_benchmark_runner(f"http://127.0.0.1:{server.port}")
        results = {
            scenario_id: runner.run_scenario(scenario_id) for scenario_id in selected_scenarios
        }
    finally:
        server.stop()
    return _write_benchmark_reports(results)


def _write_benchmark_reports(results: dict[str, Any]) -> tuple[Path, Path]:
    reporter = _load_benchmark_reporter()
    reports_dir = _benchmark_reports_dir()
    report_name = _SERVICE.report_stem()
    json_path = reports_dir / f"{report_name}.json"
    markdown_path = reports_dir / f"{report_name}.md"
    scenario_results = {
        scenario_id: result.evaluation_result for scenario_id, result in results.items()
    }
    efficiency = {
        scenario_id: {
            key: value
            for key, value in result.execution_summary.items()
            if key == "total_graph_steps"
        }
        for scenario_id, result in results.items()
    }
    reporter.generate_json_report(
        scenario_results,
        output_path=json_path,
        git_commit=_benchmark_git_commit(),
        efficiency_data=efficiency,
    )
    compare_results = None
    try:
        compare_results = _compare_new_benchmark_report(json_path)
    except FileNotFoundError:
        compare_results = None
    reporter.generate_markdown_report(
        scenario_results,
        output_path=markdown_path,
        compare_results=compare_results,
    )
    return json_path, markdown_path


def benchmark_command(
    all_scenarios: bool = typer.Option(False, "--all", help="运行全部 benchmark 场景"),
    scenario: list[str] = typer.Option(
        [],
        "--scenario",
        "-s",
        help="运行一个或多个 benchmark 场景，可重复传入",
    ),
    list_only: bool = typer.Option(False, "--list", help="列出可用 benchmark 场景"),
    report: str = typer.Option("", "--report", help="查看报告，当前支持 latest"),
    compare_last: bool = typer.Option(False, "--compare-last", help="比较最近两次 benchmark 报告"),
) -> None:
    """运行或查看 benchmark 报告。"""
    try:
        if list_only:
            console.print("\n".join(_list_benchmark_scenarios()))
            return
        if report:
            if report != "latest":
                raise ValueError("Only `--report latest` is supported.")
            console.print(_render_latest_benchmark_report())
            return
        selected = list(scenario)
        if compare_last and not all_scenarios and not selected:
            console.print(
                json.dumps(_compare_latest_benchmark_reports(), ensure_ascii=False, indent=2)
            )
            return
        if all_scenarios == bool(selected):
            raise ValueError("Use exactly one of `--all` or `--scenario`.")
        cli_runtime.bootstrap_cli_logging(output_dir=str(_benchmark_reports_dir().parent))
        selected = _list_benchmark_scenarios() if all_scenarios else selected
        json_path, markdown_path = _run_benchmark_and_write_reports(selected)
        console.print(f"Benchmark report written: {json_path}")
        console.print(f"Benchmark summary written: {markdown_path}")
        if compare_last:
            console.print(
                json.dumps(_compare_new_benchmark_report(json_path), ensure_ascii=False, indent=2)
            )
    except (FileNotFoundError, ValueError) as exc:
        console.print(Panel(f"[red]{exc}[/red]", title="Benchmark 错误", style="red"))
        raise typer.Exit(1) from exc
    except Exception as exc:
        console.print(Panel(f"[red]{exc}[/red]", title="Benchmark 失败", style="red"))
        raise typer.Exit(1) from exc
