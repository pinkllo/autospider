from __future__ import annotations

import typer

from ._rendering import console
from ._runtime import (
    cli_runtime,
    inspect_graph as _inspect_graph,
    invoke_graph as _invoke_graph,
    parse_resume_payload as _parse_resume_payload,
    raise_if_graph_failed as _raise_if_graph_failed,
    resume_graph as _resume_graph,
    run_async_safely,
)
from .benchmark import (
    _benchmark_git_commit,
    _benchmark_json_reports,
    _benchmark_paths,
    _benchmark_reports_dir,
    _build_benchmark_runner,
    _compare_latest_benchmark_reports,
    _compare_new_benchmark_report,
    _last_two_benchmark_reports,
    _latest_benchmark_report_path,
    _list_benchmark_scenarios,
    _load_benchmark_reporter,
    _load_benchmark_runner,
    _render_latest_benchmark_report,
    _run_benchmark_and_write_reports,
    _write_benchmark_reports,
    benchmark_command,
)
from .chat_pipeline import chat_pipeline_command
from .doctor import doctor_command
from .redis_ops import db_init_command
from .resume import resume_graph_command

app = typer.Typer(name="autospider", help="AutoSpider CLI - 采集与配置工具", add_completion=False)
app.command("chat-pipeline")(chat_pipeline_command)
app.command("doctor")(doctor_command)
app.command("benchmark")(benchmark_command)
app.command("db-init")(db_init_command)
app.command("resume")(resume_graph_command)


def main() -> None:
    app()


__all__ = [
    "_benchmark_git_commit",
    "_benchmark_json_reports",
    "_benchmark_paths",
    "_benchmark_reports_dir",
    "_build_benchmark_runner",
    "_compare_latest_benchmark_reports",
    "_compare_new_benchmark_report",
    "_inspect_graph",
    "_invoke_graph",
    "_last_two_benchmark_reports",
    "_latest_benchmark_report_path",
    "_list_benchmark_scenarios",
    "_load_benchmark_reporter",
    "_load_benchmark_runner",
    "_parse_resume_payload",
    "_raise_if_graph_failed",
    "_render_latest_benchmark_report",
    "_resume_graph",
    "_run_benchmark_and_write_reports",
    "_write_benchmark_reports",
    "app",
    "benchmark_command",
    "chat_pipeline_command",
    "cli_runtime",
    "console",
    "db_init_command",
    "doctor_command",
    "main",
    "resume_graph_command",
    "run_async_safely",
]
