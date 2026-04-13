from __future__ import annotations

import importlib
import shutil
import sys
import tempfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

pytestmark = pytest.mark.smoke

REPO_ROOT = Path(__file__).resolve().parents[1]

_HEAVY_PREFIXES = (
    "autospider.cli",
    "autospider.cli_runtime",
    "autospider.graph",
    "autospider.common.db.engine",
    "autospider.domain.fields",
)


def _purge_modules() -> None:
    for module_name in list(sys.modules):
        if module_name.startswith(_HEAVY_PREFIXES):
            sys.modules.pop(module_name, None)


def _fresh_import_cli():
    _purge_modules()
    return importlib.import_module("autospider.cli")


@pytest.fixture()
def repo_tmp_dir() -> Path:
    base_dir = REPO_ROOT / "artifacts" / "test_tmp"
    base_dir.mkdir(parents=True, exist_ok=True)
    path = Path(tempfile.mkdtemp(prefix="doctor-tests-", dir=base_dir))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def test_importing_cli_does_not_eagerly_import_graph_runtime() -> None:
    _fresh_import_cli()

    assert "autospider.graph" not in sys.modules
    assert "autospider.common.db.engine" not in sys.modules
    assert "autospider.domain.fields" not in sys.modules


def test_root_help_does_not_import_graph_runtime() -> None:
    cli = _fresh_import_cli()

    result = CliRunner().invoke(cli.app, ["--help"])

    assert result.exit_code == 0
    assert "doctor" in result.stdout
    assert "autospider.graph" not in sys.modules
    assert "autospider.common.db.engine" not in sys.modules


def test_doctor_command_reports_failure_without_importing_graph_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli = _fresh_import_cli()
    cli_runtime = cli.cli_runtime

    monkeypatch.setattr(
        cli_runtime,
        "run_doctor_checks",
        lambda: [
            cli_runtime.DoctorCheckResult(name="database", status="ok", detail="ok"),
            cli_runtime.DoctorCheckResult(name="redis", status="fail", detail="unreachable"),
            cli_runtime.DoctorCheckResult(
                name="graph_checkpoint",
                status="skipped",
                detail="GRAPH_CHECKPOINT_ENABLED=false",
            ),
        ],
    )

    result = CliRunner().invoke(cli.app, ["doctor"])

    assert result.exit_code == 1
    assert "Core Status" in result.stdout
    assert "Runtime Status" in result.stdout
    assert "database" in result.stdout
    assert "redis" in result.stdout
    assert "graph_checkpoint" in result.stdout
    assert "runtime_log" in result.stdout
    assert "llm_trace" in result.stdout
    assert "unreachable" in result.stdout
    assert "autospider.graph" not in sys.modules


def test_doctor_command_displays_runtime_paths_from_repo_root(
    monkeypatch: pytest.MonkeyPatch,
    repo_tmp_dir: Path,
) -> None:
    cli = _fresh_import_cli()
    cli_runtime = cli.cli_runtime

    monkeypatch.chdir(repo_tmp_dir)
    monkeypatch.setenv("LOG_FILE", "output/__pytest__/doctor.log")
    monkeypatch.setenv("LLM_TRACE_ENABLED", "false")
    monkeypatch.setenv("LLM_TRACE_FILE", "output/__pytest__/doctor-trace.jsonl")
    monkeypatch.setattr(
        cli_runtime,
        "run_doctor_checks",
        lambda: [cli_runtime.DoctorCheckResult(name="database", status="ok", detail="ok")],
    )

    result = CliRunner().invoke(cli.app, ["doctor"])

    expected_log = str((REPO_ROOT / "output" / "__pytest__" / "doctor.log").resolve())
    expected_trace = str((REPO_ROOT / "output" / "__pytest__" / "doctor-trace.jsonl").resolve())
    cwd_log = str((repo_tmp_dir / "output" / "__pytest__" / "doctor.log").resolve())

    assert result.exit_code == 0
    assert "Runtime Status" in result.stdout
    assert expected_log in result.stdout
    assert expected_trace in result.stdout
    assert cwd_log not in result.stdout
