from __future__ import annotations

import json
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def render_generated_fields_table(fields: list[Any]) -> Table:
    table = Table(title="AI 生成字段")
    table.add_column("name", style="cyan")
    table.add_column("description", style="green")
    table.add_column("type", style="magenta")
    table.add_column("required", style="yellow")
    table.add_column("example", style="blue")
    for field in fields:
        table.add_row(
            str(getattr(field, "name", "") or ""),
            str(getattr(field, "description", "") or ""),
            str(getattr(field, "data_type", "text") or "text"),
            "是" if bool(getattr(field, "required", False)) else "否",
            str(getattr(field, "example", "") or ""),
        )
    return table


def render_doctor_section(section: Any) -> bool:
    console.print(f"[bold]{section.title}[/bold]")
    table = Table(title=f"AutoSpider Doctor / {section.title}")
    table.add_column("check", style="cyan")
    table.add_column("status", style="bold")
    table.add_column("detail", style="white", overflow="fold")
    has_failure = False
    for check in section.checks:
        status = str(check.status or "").strip().lower() or "unknown"
        style = {"ok": "green", "fail": "red", "skipped": "yellow"}.get(status, "white")
        table.add_row(check.name, f"[{style}]{status}[/{style}]", check.detail)
        has_failure = has_failure or status == "fail"
    console.print(table)
    return has_failure


def print_graph_interrupted(result: dict[str, Any]) -> None:
    console.print(
        Panel(
            f"[yellow]线程仍处于中断状态[/yellow]\n\n"
            f"thread_id: {result.get('thread_id', '')}\n"
            f"interrupts: {json.dumps(list(result.get('interrupts') or []), ensure_ascii=False, indent=2)}",
            title="执行中断",
            style="yellow",
        )
    )


def print_chat_pipeline_result(graph_result: dict[str, Any], *, output_dir: str) -> None:
    summary = graph_result.get("summary") or {}
    console.print(
        Panel(
            f"[green]流水线完成（multi）[/green]\n\n"
            f"总子任务数: {summary.get('total', 0)}\n"
            f"成功: {summary.get('completed', 0)}\n"
            f"失败: {summary.get('failed', 0)}\n"
            f"总采集数: {summary.get('total_collected', 0)}\n"
            f"合并结果: {output_dir}/merged_results.jsonl\n"
            f"恢复线程: {summary.get('thread_id') or graph_result.get('thread_id', '')}",
            title="执行完成",
            style="green",
        )
    )


def format_optional_bool(value: Any) -> str:
    if value is None:
        return "未指定"
    return "True" if bool(value) else "False"
