from __future__ import annotations

import sys

import pytest

from tests.cli_test_support import fresh_import_cli, purge_modules

pytestmark = pytest.mark.smoke

_HEAVY_PREFIXES = (
    "autospider.interface.cli",
    "autospider.legacy.cli_runtime",
    "autospider.legacy.graph",
    "autospider.legacy.common.db.engine",
    "autospider.legacy.domain.fields",
)


def _purge_modules() -> None:
    purge_modules()
    for module_name in list(sys.modules):
        if module_name.startswith(_HEAVY_PREFIXES):
            sys.modules.pop(module_name, None)


@pytest.fixture(autouse=True)
def _restore_heavy_modules_after_test():
    saved = {
        module_name: module
        for module_name, module in sys.modules.items()
        if module_name.startswith(_HEAVY_PREFIXES)
    }
    yield
    _purge_modules()
    sys.modules.update(saved)


def test_importing_cli_does_not_eagerly_import_graph_runtime() -> None:
    fresh_import_cli()

    assert "autospider.legacy.graph" not in sys.modules
    assert "autospider.legacy.common.db.engine" not in sys.modules
    assert "autospider.legacy.domain.fields" not in sys.modules


def test_root_help_registration_does_not_import_graph_runtime() -> None:
    cli = fresh_import_cli()
    command_names = {command.name for command in cli.app.registered_commands}

    assert "doctor" in command_names
    assert "autospider.legacy.graph" not in sys.modules
    assert "autospider.legacy.common.db.engine" not in sys.modules


def test_doctor_command_reports_failure_without_importing_graph_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli = fresh_import_cli()
    cli_runtime = cli.cli_runtime
    fake_section = cli_runtime.DoctorCheckSection(
        name="core",
        title="Core Status",
        checks=(
            cli_runtime.DoctorCheckResult(name="database", status="ok", detail="ok"),
            cli_runtime.DoctorCheckResult(name="redis", status="fail", detail="unreachable"),
        ),
    )
    monkeypatch.setattr(cli_runtime, "build_doctor_sections", lambda: [fake_section])

    with pytest.raises(Exception) as exc_info:
        cli.doctor_command()

    assert getattr(exc_info.value, "exit_code", None) == 1
    assert "autospider.legacy.graph" not in sys.modules
