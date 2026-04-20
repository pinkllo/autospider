from __future__ import annotations

import importlib
import inspect
import shutil
import sys
import tempfile
import types
from pathlib import Path

import pytest

pytestmark = pytest.mark.smoke

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"

_PURGE_PREFIXES = (
    "autospider.interface.cli",
    "autospider.legacy.cli_runtime",
    "autospider.legacy.graph",
    "autospider.platform.persistence.sql.orm.engine",
    "autospider.legacy.domain.fields",
    "typer",
    "click",
    "rich",
)


def _purge_modules() -> None:
    for module_name in list(sys.modules):
        if module_name.startswith(_PURGE_PREFIXES):
            sys.modules.pop(module_name, None)


def _install_cli_stubs() -> None:
    typer_module = types.ModuleType("typer")

    class FakeContext:
        def get_parameter_source(self, _name: str):
            return None

    class FakeOption:
        def __init__(self, default=None, *args, **kwargs):
            self.default = default
            self.param_decls = args
            self.kwargs = kwargs

        def __repr__(self) -> str:
            return repr(self.default)

    class FakeExit(Exception):
        def __init__(self, code: int = 0) -> None:
            super().__init__(code)
            self.exit_code = code

    class FakeTyper:
        def __init__(self, *args, **kwargs) -> None:
            self.registered_commands: list[types.SimpleNamespace] = []

        def command(self, name: str | None = None, *args, **kwargs):
            def decorator(func):
                self.registered_commands.append(
                    types.SimpleNamespace(name=name or func.__name__, callback=func)
                )
                return func

            return decorator

        def __call__(self, *args, **kwargs) -> None:
            return None

    typer_module.Typer = FakeTyper
    typer_module.Option = lambda default=None, *args, **kwargs: FakeOption(default, *args, **kwargs)
    typer_module.prompt = lambda *args, **kwargs: kwargs.get("default", "")
    typer_module.confirm = lambda *args, **kwargs: kwargs.get("default", False)
    typer_module.Exit = FakeExit
    typer_module.Context = FakeContext

    click_module = types.ModuleType("click")
    click_core = types.ModuleType("click.core")

    class ParameterSource:
        DEFAULT = "DEFAULT"
        DEFAULT_MAP = "DEFAULT_MAP"

    click_core.ParameterSource = ParameterSource

    rich_module = types.ModuleType("rich")
    rich_console = types.ModuleType("rich.console")
    rich_panel = types.ModuleType("rich.panel")
    rich_table = types.ModuleType("rich.table")
    rich_text = types.ModuleType("rich.text")

    class Console:
        def print(self, *args, **kwargs) -> None:
            return None

    class Panel:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

    class Table:
        def __init__(self, *args, **kwargs) -> None:
            self.rows: list[tuple] = []

        def add_column(self, *args, **kwargs) -> None:
            return None

        def add_row(self, *args, **kwargs) -> None:
            self.rows.append(args)

    class Text(str):
        pass

    rich_console.Console = Console
    rich_panel.Panel = Panel
    rich_table.Table = Table
    rich_text.Text = Text

    sys.modules["typer"] = typer_module
    sys.modules["click"] = click_module
    sys.modules["click.core"] = click_core
    sys.modules["rich"] = rich_module
    sys.modules["rich.console"] = rich_console
    sys.modules["rich.panel"] = rich_panel
    sys.modules["rich.table"] = rich_table
    sys.modules["rich.text"] = rich_text


def _fresh_import_cli():
    _purge_modules()
    _install_cli_stubs()
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))
    return importlib.import_module("autospider.interface.cli")


@pytest.fixture(autouse=True)
def _restore_modules_after_test():
    saved = {
        module_name: module
        for module_name, module in sys.modules.items()
        if module_name.startswith(_PURGE_PREFIXES)
    }
    yield
    _purge_modules()
    sys.modules.update(saved)


@pytest.fixture()
def repo_tmp_dir() -> Path:
    base_dir = REPO_ROOT / "artifacts" / "test_tmp"
    base_dir.mkdir(parents=True, exist_ok=True)
    path = Path(tempfile.mkdtemp(prefix="benchmark-cli-", dir=base_dir))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def test_cli_registers_benchmark_command() -> None:
    cli = _fresh_import_cli()

    command_names = {command.name for command in cli.app.registered_commands}

    assert "benchmark" in command_names


def test_benchmark_command_supports_short_s_alias_and_repeatable_scenarios() -> None:
    cli = _fresh_import_cli()

    scenario_default = inspect.signature(cli.benchmark_command).parameters["scenario"].default

    assert scenario_default.default == []
    assert "--scenario" in scenario_default.param_decls
    assert "-s" in scenario_default.param_decls


def test_list_benchmark_scenarios_returns_fixture_data_without_runtime_imports() -> None:
    cli = _fresh_import_cli()

    scenario_ids = cli._list_benchmark_scenarios()

    assert "products" in scenario_ids
    assert "categories" in scenario_ids
    assert "autospider.legacy.graph" not in sys.modules


def test_render_latest_benchmark_report_fails_without_history(
    monkeypatch: pytest.MonkeyPatch,
    repo_tmp_dir: Path,
) -> None:
    cli = _fresh_import_cli()
    benchmark_module = inspect.getmodule(cli._render_latest_benchmark_report)
    assert benchmark_module is not None
    monkeypatch.setattr(benchmark_module, "_benchmark_reports_dir", lambda: repo_tmp_dir)

    with pytest.raises(FileNotFoundError, match="No benchmark reports found"):
        cli._render_latest_benchmark_report()

    assert "autospider.legacy.graph" not in sys.modules


def test_compare_latest_benchmark_reports_fails_without_history(
    monkeypatch: pytest.MonkeyPatch,
    repo_tmp_dir: Path,
) -> None:
    cli = _fresh_import_cli()
    benchmark_module = inspect.getmodule(cli._compare_latest_benchmark_reports)
    assert benchmark_module is not None
    monkeypatch.setattr(benchmark_module, "_benchmark_reports_dir", lambda: repo_tmp_dir)

    with pytest.raises(FileNotFoundError, match="Need at least two benchmark reports"):
        cli._compare_latest_benchmark_reports()

    assert "autospider.legacy.graph" not in sys.modules


def test_benchmark_command_runs_then_compares_when_compare_last_is_combined(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli = _fresh_import_cli()
    calls: list[tuple[str, object]] = []
    benchmark_module = inspect.getmodule(cli.benchmark_command)
    assert benchmark_module is not None

    monkeypatch.setattr(
        cli.cli_runtime, "bootstrap_cli_logging", lambda **kwargs: calls.append(("log", kwargs))
    )
    monkeypatch.setattr(
        benchmark_module, "_list_benchmark_scenarios", lambda: ["products", "categories"]
    )
    monkeypatch.setattr(
        benchmark_module,
        "_run_benchmark_and_write_reports",
        lambda selected: calls.append(("run", list(selected)))
        or (Path("previous.json"), Path("latest.md")),
    )
    monkeypatch.setattr(
        benchmark_module,
        "_compare_new_benchmark_report",
        lambda path: calls.append(("compare", path)) or {"products": {"status": "pass"}},
    )

    cli.benchmark_command(
        all_scenarios=True,
        scenario=(),
        list_only=False,
        report="",
        compare_last=True,
    )

    assert calls[1] == ("run", ["products", "categories"])
    assert calls[2] == ("compare", Path("previous.json"))


def test_benchmark_command_accepts_multiple_scenarios(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli = _fresh_import_cli()
    captured: list[str] = []
    benchmark_module = inspect.getmodule(cli.benchmark_command)
    assert benchmark_module is not None

    monkeypatch.setattr(cli.cli_runtime, "bootstrap_cli_logging", lambda **kwargs: None)
    monkeypatch.setattr(
        benchmark_module,
        "_run_benchmark_and_write_reports",
        lambda selected: captured.extend(selected) or (Path("latest.json"), Path("latest.md")),
    )

    cli.benchmark_command(
        all_scenarios=False,
        scenario=("products", "categories"),
        list_only=False,
        report="",
        compare_last=False,
    )

    assert captured == ["products", "categories"]
