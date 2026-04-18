from __future__ import annotations

import importlib

from . import normalize_help_surface

ROOT_SNAPSHOT = {
    "usage": "Usage: autospider [OPTIONS] COMMAND [ARGS]...",
    "description": "AutoSpider CLI - 采集与配置工具",
    "options": ["--help"],
    "commands": ["chat-pipeline", "doctor", "benchmark", "db-init", "resume"],
}

CHAT_PIPELINE_SNAPSHOT = {
    "usage": "Usage: autospider chat-pipeline [OPTIONS]",
    "description": "全自然语言多轮交互后执行流水线。",
    "options": [
        "--request",
        "-r",
        "--max-turns",
        "--field-explore-count",
        "--field-validate-count",
        "--max-pages",
        "--target-url-count",
        "--consumer-concurrency",
        "--serial",
        "--no-serial",
        "--max-concurrent",
        "--headless",
        "--no-headless",
        "--output",
        "-o",
        "--thread-id",
        "--help",
    ],
    "commands": [],
}

RESUME_SNAPSHOT = {
    "usage": "Usage: autospider resume [OPTIONS]",
    "description": "恢复已持久化的 LangGraph 线程。",
    "options": ["--thread-id", "--resume-json", "--help"],
    "commands": [],
}

DOCTOR_SNAPSHOT = {
    "usage": "Usage: autospider doctor [OPTIONS]",
    "description": "检查 Redis-only CLI 的本地运行前置条件。",
    "options": ["--help"],
    "commands": [],
}

BENCHMARK_SNAPSHOT = {
    "usage": "Usage: autospider benchmark [OPTIONS]",
    "description": "运行或查看 benchmark 报告。",
    "options": ["--all", "--scenario", "-s", "--list", "--report", "--compare-last", "--help"],
    "commands": [],
}


def test_cli_help_surfaces_match_contract_snapshots() -> None:
    cli_module = importlib.import_module("autospider.cli")
    runner = _load_cli_runner()
    commands = {
        "root": [],
        "chat-pipeline": ["chat-pipeline"],
        "resume": ["resume"],
        "doctor": ["doctor"],
        "benchmark": ["benchmark"],
    }
    snapshots = {
        "root": ROOT_SNAPSHOT,
        "chat-pipeline": CHAT_PIPELINE_SNAPSHOT,
        "resume": RESUME_SNAPSHOT,
        "doctor": DOCTOR_SNAPSHOT,
        "benchmark": BENCHMARK_SNAPSHOT,
    }

    for name, args in commands.items():
        result = runner.invoke(cli_module.app, [*args, "--help"])
        assert result.exit_code == 0
        assert normalize_help_surface(result.stdout) == snapshots[name]


def _load_cli_runner():
    from typer.testing import CliRunner

    return CliRunner()
