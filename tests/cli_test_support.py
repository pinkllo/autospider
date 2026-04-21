from __future__ import annotations

import importlib
import inspect
import logging
import sys
import types
from pathlib import Path
from typing import Any

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"

_PURGE_PREFIXES = (
    "autospider.interface.cli",
    "autospider.interface",
    "autospider.interface.cli._runtime_support",
    "autospider.interface.cli._legacy_runtime",
    "autospider.composition.graph",
    "autospider.platform.persistence.sql.orm.engine",
    "autospider.contexts.collection.domain.fields",
    "typer",
    "click",
    "rich",
)


def purge_modules() -> None:
    for module_name in list(sys.modules):
        if module_name.startswith(_PURGE_PREFIXES):
            sys.modules.pop(module_name, None)


def install_cli_stubs() -> None:
    typer_module = types.ModuleType("typer")

    class FakeContext:
        def get_parameter_source(self, _name: str):
            return None

    class FakeOption:
        def __init__(self, default=None, *args, **kwargs):
            self.default = default
            self.param_decls = args
            self.kwargs = kwargs

    class FakeExit(Exception):
        def __init__(self, code: int = 0) -> None:
            super().__init__(code)
            self.exit_code = code

    class FakeTyper:
        def __init__(self, *args, **kwargs) -> None:
            self.registered_commands: list[types.SimpleNamespace] = []
            self.info = types.SimpleNamespace(
                name=kwargs.get("name", ""),
                help=kwargs.get("help", ""),
            )

        def command(self, name: str | None = None, *args, **kwargs):
            def decorator(func):
                self.registered_commands.append(
                    types.SimpleNamespace(
                        name=name or func.__name__,
                        callback=func,
                        help=(
                            (inspect.getdoc(func) or "").splitlines()[0]
                            if inspect.getdoc(func)
                            else ""
                        ),
                    )
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
    rich_logging = types.ModuleType("rich.logging")
    rich_panel = types.ModuleType("rich.panel")
    rich_table = types.ModuleType("rich.table")

    class Console:
        def __init__(self) -> None:
            self.messages: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

        def print(self, *args, **kwargs) -> None:
            self.messages.append((args, kwargs))

    class Panel:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

    class RichHandler(logging.Handler):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__()
            self.args = args
            self.kwargs = kwargs

        def emit(self, _record: logging.LogRecord) -> None:
            return None

    class Table:
        def __init__(self, *args, **kwargs) -> None:
            self.rows: list[tuple[Any, ...]] = []

        def add_column(self, *args, **kwargs) -> None:
            return None

        def add_row(self, *args, **kwargs) -> None:
            self.rows.append(args)

    rich_console.Console = Console
    rich_logging.RichHandler = RichHandler
    rich_panel.Panel = Panel
    rich_table.Table = Table

    sys.modules["typer"] = typer_module
    sys.modules["click"] = click_module
    sys.modules["click.core"] = click_core
    sys.modules["rich"] = rich_module
    sys.modules["rich.console"] = rich_console
    sys.modules["rich.logging"] = rich_logging
    sys.modules["rich.panel"] = rich_panel
    sys.modules["rich.table"] = rich_table


def fresh_import_cli():
    purge_modules()
    install_cli_stubs()
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))
    return importlib.import_module("autospider.interface.cli")


def fresh_import_legacy_cli():
    purge_modules()
    install_cli_stubs()
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))
    return importlib.import_module("autospider.interface.cli._legacy_cli")


def fresh_import_top_level_cli():
    purge_modules()
    install_cli_stubs()
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))
    return importlib.import_module("autospider.cli")


def fresh_import_interface_cli():
    purge_modules()
    install_cli_stubs()
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))
    return importlib.import_module("autospider.interface.cli")


def help_surface(module, command_name: str | None = None) -> dict[str, Any]:
    app = module.app
    if command_name is None:
        return {
            "usage": "Usage: autospider [OPTIONS] COMMAND [ARGS]...",
            "description": str(getattr(app.info, "help", "") or ""),
            "options": ["--help"],
            "commands": [command.name for command in app.registered_commands],
        }
    command = next(item for item in app.registered_commands if item.name == command_name)
    return {
        "usage": f"Usage: autospider {command_name} [OPTIONS]",
        "description": command.help,
        "options": _command_options(command.callback),
        "commands": [],
    }


def _command_options(callback) -> list[str]:
    options: list[str] = []
    for parameter in inspect.signature(callback).parameters.values():
        default = parameter.default
        for decl in getattr(default, "param_decls", ()):
            for item in _split_decl(decl):
                if item not in options:
                    options.append(item)
    options.append("--help")
    return options


def _split_decl(decl: str) -> list[str]:
    if "/" not in decl:
        return [decl]
    return [item for item in decl.split("/") if item]

