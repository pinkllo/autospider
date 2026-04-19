from __future__ import annotations

import typer

from ._rendering import console
from ._runtime import cli_runtime


def db_init_command(
    reset: bool = typer.Option(
        False,
        "--reset",
        help="先删除现有任务相关表，再按当前 PostgreSQL 模型重建。",
    ),
) -> None:
    """初始化 PostgreSQL schema。"""
    cli_runtime.bootstrap_cli_logging()
    cli_runtime.init_database(reset=reset)
    console.print("[green]数据库 schema 已初始化[/green]")
