from __future__ import annotations

import json
import logging

import typer
from rich.panel import Panel

from ._rendering import console, print_graph_interrupted
from ._runtime import cli_runtime, parse_resume_payload, raise_if_graph_failed, resume_graph
from .chat_pipeline import _continue_chat_interrupts, resume_via_current_state

logger = logging.getLogger(__name__)


def resume_graph_command(
    thread_id: str = typer.Option(..., "--thread-id", help="需要恢复的 LangGraph 线程 ID"),
    resume_json: str = typer.Option("", "--resume-json", help="interrupt 恢复载荷（JSON）。留空时按静态断点继续。"),
) -> None:
    """恢复已持久化的 LangGraph 线程。"""
    try:
        cli_runtime.bootstrap_cli_logging()
        resume_payload, has_payload = parse_resume_payload(resume_json)
        result = (
            resume_graph(thread_id, resume=resume_payload, use_command=True)
            if has_payload
            else resume_via_current_state(thread_id)
        )
        if str(result.get("status") or "") == "interrupted":
            result = _continue_chat_interrupts(result)
        raise_if_graph_failed(result)
        status = str(result.get("status") or "")
        if status == "interrupted":
            print_graph_interrupted(result)
            return
        summary = result.get("summary") or {}
        console.print(
            Panel(
                f"[green]线程恢复完成[/green]\n\n"
                f"thread_id: {result.get('thread_id', '')}\n"
                f"entry_mode: {result.get('entry_mode', '')}\n"
                f"status: {status}\n"
                f"summary: {json.dumps(summary, ensure_ascii=False, indent=2)}",
                title="Resume 完成",
                style="green",
            )
        )
    except KeyboardInterrupt:
        logger.info("用户中断")
        raise typer.Exit(130)
    except json.JSONDecodeError as exc:
        console.print(Panel(f"[red]resume-json 不是合法 JSON: {exc}[/red]", title="输入错误", style="red"))
        raise typer.Exit(1) from exc
    except Exception as exc:
        console.print(Panel(f"[red]{exc}[/red]", title="恢复失败", style="red"))
        raise typer.Exit(1) from exc
