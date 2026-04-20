from __future__ import annotations

import logging
from typing import Any

import typer
from click.core import ParameterSource
from rich.panel import Panel

from ._rendering import (
    console,
    format_optional_bool,
    print_chat_pipeline_result,
    print_graph_interrupted,
    render_generated_fields_table,
)
from ._runtime import (
    cli_runtime,
    inspect_graph,
    invoke_graph,
    raise_if_graph_failed,
    resume_graph,
)

logger = logging.getLogger(__name__)
_GRAPH_THREAD_ID_HELP = "LangGraph 线程 ID。为空时自动生成，可用于后续 resume。"
_PIPELINE_MODE_REDIS = "redis"


def _serialize_fields(fields: list[Any]) -> list[dict[str, Any]]:
    return cli_runtime.serialize_field_definitions_payload(fields)


def _field_definitions_from_mappings(raw_fields: list[dict[str, Any]]) -> list[Any]:
    return cli_runtime.build_field_definitions(raw_fields)


def _option_was_explicit(ctx: typer.Context, option_name: str) -> bool:
    source = ctx.get_parameter_source(option_name)
    return source not in {None, ParameterSource.DEFAULT, ParameterSource.DEFAULT_MAP}


def _optional_bool_from_cli(ctx: typer.Context, option_name: str, value: bool) -> bool | None:
    if not _option_was_explicit(ctx, option_name):
        return None
    return value


def _edit_chat_review_task(task_payload: dict[str, Any]) -> dict[str, Any]:
    updated_task = dict(task_payload)
    fields = _field_definitions_from_mappings(list(updated_task.get("fields") or []))
    if not fields:
        raise ValueError("当前没有可编辑字段。")
    console.print(render_generated_fields_table(fields))
    updated_task["fields"] = _serialize_fields(fields)
    return updated_task


def _primary_interrupt_payload(result: dict[str, Any]) -> dict[str, Any] | None:
    for item in list(result.get("interrupts") or []):
        if isinstance(item, dict) and isinstance(item.get("value"), dict):
            return item["value"]
    return None


def _handle_chat_clarification_interrupt(payload: dict[str, Any]) -> dict[str, Any]:
    question = str(payload.get("question") or "请补充更明确的采集目标、URL 或字段要求。")
    turn = payload.get("turn")
    max_turns = payload.get("max_turns")
    title = f"AI 澄清问题 ({turn}/{max_turns})" if turn and max_turns else "AI 澄清问题"
    console.print(Panel(question, title=title, style="yellow"))
    answer = typer.prompt("你的回答").strip()
    return {"answer": answer or "请按常见默认方案继续，并明确你的默认假设。"}


def _handle_chat_review_interrupt(payload: dict[str, Any]) -> dict[str, Any]:
    task = dict(payload.get("clarified_task") or {})
    effective = dict(payload.get("effective_options") or {})
    fields = _field_definitions_from_mappings(list(task.get("fields") or []))
    console.print(
        Panel(
            f"[bold]识别意图:[/bold] {task.get('intent') or '未提供'}\n"
            f"[bold]列表页 URL:[/bold] {task.get('list_url') or ''}\n"
            f"[bold]任务描述:[/bold] {task.get('task_description') or ''}\n"
            f"[bold]字段数量:[/bold] {len(fields)}\n"
            f"[bold]最大翻页:[/bold] {effective.get('max_pages') if effective.get('max_pages') is not None else '默认'}\n"
            f"[bold]目标 URL 数:[/bold] {effective.get('target_url_count') if effective.get('target_url_count') is not None else '默认'}\n"
            f"[bold]字段探索数:[/bold] {effective.get('field_explore_count') if effective.get('field_explore_count') is not None else '默认'}\n"
            f"[bold]字段校验数:[/bold] {effective.get('field_validate_count') if effective.get('field_validate_count') is not None else '默认'}\n"
            f"[bold]消费者并发:[/bold] {effective.get('consumer_concurrency') if effective.get('consumer_concurrency') is not None else '默认'}\n"
            f"[bold]串行模式:[/bold] {bool(effective.get('serial_mode', False))}\n"
            f"[bold]执行后端:[/bold] {_PIPELINE_MODE_REDIS}\n"
            f"[bold]执行引擎:[/bold] {effective.get('execution_mode') or 'multi'}\n"
            f"[bold]多任务并发:[/bold] {effective.get('max_concurrent') if effective.get('max_concurrent') is not None else '默认'}\n"
            f"[bold]无头模式:[/bold] {format_optional_bool(effective.get('headless'))}\n"
            f"[bold]输出目录:[/bold] {effective.get('output_dir') or 'output'}",
            title="AI 生成任务配置",
            style="cyan",
        )
    )
    if fields:
        console.print(render_generated_fields_table(fields))
    action = typer.prompt(
        "请选择下一步 [1=开始执行, 2=补充需求并重新生成, 3=手动修改字段后执行, 4=取消]",
        default="1",
    ).strip()
    if action == "1":
        return {"action": "approve"}
    if action == "2":
        supplement = typer.prompt("请输入补充要求").strip()
        return {
            "action": "supplement",
            "message": supplement or "请按常见默认方案继续，并明确你的默认假设。",
        }
    if action == "3":
        return {"action": "override_task", "task": _edit_chat_review_task(task)}
    if action == "4":
        return {"action": "cancel"}
    console.print("[yellow]无效选项，已按开始执行处理。[/yellow]")
    return {"action": "approve"}


def _handle_browser_intervention_interrupt(payload: dict[str, Any]) -> dict[str, Any]:
    message = str(payload.get("message") or "请先处理浏览器中的异常，再继续恢复。")
    console.print(Panel(f"[yellow]{message}[/yellow]", title="浏览器人工介入", style="yellow"))
    typer.confirm("处理完成后继续 resume？", default=True, abort=True)
    return {"action": "continue", "intervention_type": str(payload.get("intervention_type") or "")}


def _handle_history_task_select_interrupt(payload: dict[str, Any]) -> dict[str, Any]:
    options = list(payload.get("options") or [])
    if not options:
        return {"choice": 1}
    console.print(
        Panel(
            str(payload.get("message") or "检测到历史采集任务，请选择："),
            title="历史任务匹配",
            style="yellow",
        )
    )
    for option in options:
        console.print(f"  [cyan]{option.get('index', '')}[/cyan]. {option.get('label', '')}")
    choice = typer.prompt(f"请输入选项序号（1-{len(options)}）", default="1").strip()
    return {"choice": int(choice)}


def _continue_chat_interrupts(result: dict[str, Any]) -> dict[str, Any]:
    current = dict(result)
    while str(current.get("status") or "") == "interrupted":
        payload = _primary_interrupt_payload(current)
        if not isinstance(payload, dict):
            break
        interrupt_type = str(payload.get("type") or "").strip().lower()
        if interrupt_type == "chat_clarification":
            resume_payload = _handle_chat_clarification_interrupt(payload)
        elif interrupt_type == "chat_review":
            resume_payload = _handle_chat_review_interrupt(payload)
        elif interrupt_type == "browser_intervention":
            resume_payload = _handle_browser_intervention_interrupt(payload)
        elif interrupt_type == "history_task_select":
            resume_payload = _handle_history_task_select_interrupt(payload)
        else:
            break
        thread_id = str(current.get("thread_id") or "")
        if not thread_id:
            break
        current = resume_graph(thread_id, resume=resume_payload, use_command=True)
    return current


def chat_pipeline_command(
    ctx: typer.Context,
    request: str = typer.Option(
        "", "--request", "-r", help="初始自然语言需求（可为空，程序会交互询问）"
    ),
    max_turns: int = typer.Option(6, "--max-turns", help="多轮澄清的最大轮数"),
    field_explore_count: int | None = typer.Option(
        None, "--field-explore-count", help="字段探索数量（默认取配置）"
    ),
    field_validate_count: int | None = typer.Option(
        None, "--field-validate-count", help="字段校验数量（默认取配置）"
    ),
    max_pages: int | None = typer.Option(
        None, "--max-pages", help="列表页最大翻页次数（可覆盖 AI 推断）"
    ),
    target_url_count: int | None = typer.Option(
        None, "--target-url-count", help="目标采集 URL 数量（可覆盖 AI 推断）"
    ),
    consumer_concurrency: int | None = typer.Option(
        None, "--consumer-concurrency", help="详情抽取消费者并发数（默认取配置）"
    ),
    serial_mode: bool = typer.Option(
        False, "--serial/--no-serial", help="显式串行模式：本机测试时强制关闭多任务并发和详情页并发"
    ),
    max_concurrent: int | None = typer.Option(
        None, "--max-concurrent", help="多分类子任务最大并发数（用于 multi）"
    ),
    headless: bool = typer.Option(
        False, "--headless/--no-headless", help="是否使用无头模式（默认读取 .env HEADLESS）"
    ),
    output_dir: str = typer.Option("output", "--output", "-o", help="输出目录"),
    thread_id: str = typer.Option("", "--thread-id", help=_GRAPH_THREAD_ID_HELP),
) -> None:
    """全自然语言多轮交互后执行流水线。"""
    cli_runtime.bootstrap_cli_logging(output_dir=output_dir)
    if max_turns < 1:
        console.print(Panel("[red]max-turns 必须 >= 1[/red]", title="参数错误", style="red"))
        raise typer.Exit(1)
    if not _option_was_explicit(ctx, "serial_mode"):
        serial_mode = cli_runtime.get_default_serial_mode()
    initial_request = request.strip() or typer.prompt("请描述你想爬取什么（可模糊）").strip()
    if not initial_request:
        console.print(Panel("[red]需求不能为空[/red]", title="输入错误", style="red"))
        raise typer.Exit(1)
    resolved_headless = _optional_bool_from_cli(ctx, "headless", headless)
    try:
        graph_result = invoke_graph(
            "chat_pipeline",
            {
                "request": initial_request,
                "max_turns": max_turns,
                "headless": resolved_headless,
                "output_dir": output_dir,
                "max_pages": max_pages,
                "target_url_count": target_url_count,
                "consumer_concurrency": consumer_concurrency,
                "serial_mode": serial_mode,
                "field_explore_count": field_explore_count,
                "field_validate_count": field_validate_count,
                "max_concurrent": max_concurrent,
            },
            thread_id=thread_id,
        )
        graph_result = _continue_chat_interrupts(graph_result)
        raise_if_graph_failed(graph_result)
        if str(graph_result.get("status") or "") == "interrupted":
            print_graph_interrupted(graph_result)
            return
        print_chat_pipeline_result(graph_result, output_dir=output_dir)
    except KeyboardInterrupt:
        logger.info("用户中断")
        raise typer.Exit(130)
    except Exception as exc:
        console.print(Panel(f"[red]{exc}[/red]", title="执行错误", style="red"))
        raise typer.Exit(1) from exc


def resume_via_current_state(thread_id: str) -> dict[str, Any]:
    current_state = inspect_graph(thread_id)
    if str(current_state.get("status") or "") == "interrupted":
        return _continue_chat_interrupts(current_state)
    if list(current_state.get("next_nodes") or []):
        return resume_graph(thread_id, resume=None, use_command=False)
    return current_state
