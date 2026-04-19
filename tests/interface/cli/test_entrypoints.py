from __future__ import annotations

from tests.cli_test_support import fresh_import_cli, fresh_import_interface_cli


def test_legacy_cli_reexports_interface_cli_app() -> None:
    legacy_cli = fresh_import_cli()
    interface_cli = fresh_import_interface_cli()

    assert legacy_cli.app.info.name == interface_cli.app.info.name
    assert [command.name for command in legacy_cli.app.registered_commands] == [
        command.name for command in interface_cli.app.registered_commands
    ]


def test_interface_cli_help_surface_matches_public_commands() -> None:
    interface_cli = fresh_import_interface_cli()
    command_names = {command.name for command in interface_cli.app.registered_commands}

    assert "chat-pipeline" in command_names
    assert "doctor" in command_names
    assert "benchmark" in command_names
    assert "db-init" in command_names
    assert "resume" in command_names
