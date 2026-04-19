from __future__ import annotations

import typer

from ._rendering import render_doctor_section
from ._runtime import cli_runtime


def doctor_command() -> None:
    """检查 Redis-only CLI 的本地运行前置条件。"""
    cli_runtime.bootstrap_cli_logging()
    has_failure = False
    for section in cli_runtime.build_doctor_sections():
        has_failure = render_doctor_section(section) or has_failure
    if has_failure:
        raise typer.Exit(1)
