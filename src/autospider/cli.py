"""CLI 入口"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import threading
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .common.validators import validate_url, validate_task_description
from .common.exceptions import ValidationError, URLValidationError
from .common.logger import get_logger
from .field import FieldDefinition
from .graph import GraphInput, GraphRunner

# 日志器
logger = get_logger(__name__)

app = typer.Typer(
    name="autospider",
    help="AutoSpider CLI - 采集与配置工具",
    add_completion=False,
)
console = Console()
_GRAPH_THREAD_ID_HELP = "LangGraph 线程 ID。为空时自动生成，可用于后续 resume。"


def run_async_safely(coro):
    """在 CLI 同步上下文中安全执行协程。"""
    # 修改原因：CLI 中直接调用 run_async_safely，但此前未定义该方法会抛 NameError。
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # 没有运行中的事件循环，直接使用 asyncio.run
        try:
            return asyncio.run(coro)
        except KeyboardInterrupt:
            # Ctrl+C 中断时，asyncio.run 会自动清理
            raise

    # 已有运行中的事件循环，需要在新线程中创建新的事件循环
    result_holder: dict[str, object] = {"result": None, "error": None}

    def _runner():
        loop = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result_holder["result"] = loop.run_until_complete(coro)
        except KeyboardInterrupt:
            # Ctrl+C 中断，取消所有任务
            result_holder["error"] = KeyboardInterrupt("用户中断")
            if loop:
                # 取消所有待处理的任务
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                # 等待所有任务完成取消
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        except Exception as exc:  # noqa: BLE001
            result_holder["error"] = exc
        finally:
            if loop:
                try:
                    # 统一取消并回收残留后台任务，避免 loop.close() 后出现
                    # "Future exception was never retrieved" 噪音。
                    pending = list(asyncio.all_tasks(loop))
                    if pending:
                        for task in pending:
                            task.cancel()
                        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                except Exception:
                    pass
                try:
                    # 关闭所有异步生成器
                    loop.run_until_complete(loop.shutdown_asyncgens())
                    # 关闭所有异步 executor
                    loop.run_until_complete(loop.shutdown_default_executor())
                except Exception:
                    pass
                finally:
                    loop.close()
            asyncio.set_event_loop(None)

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()

    if result_holder["error"] is not None:
        raise result_holder["error"]  # type: ignore[misc]
    return result_holder["result"]


def _load_fields(fields_json: str, fields_file: str) -> list[FieldDefinition]:
    payload = ""

    if fields_file:
        path = Path(fields_file)
        if not path.exists():
            raise ValueError(f"字段定义文件不存在: {fields_file}")
        payload = path.read_text(encoding="utf-8")
    elif fields_json:
        payload = fields_json
    else:
        raise ValueError("请提供 --fields-json 或 --fields-file")

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"字段定义 JSON 解析失败: {exc}") from exc

    if not isinstance(data, list):
        raise ValueError("字段定义必须是 JSON 数组")

    fields: list[FieldDefinition] = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("字段定义必须是对象数组")

        name = item.get("name")
        description = item.get("description")
        if not name or not description:
            raise ValueError("字段定义必须包含 name 与 description")

        fields.append(
            FieldDefinition(
                name=name,
                description=description,
                required=bool(item.get("required", True)),
                data_type=item.get("data_type", "text"),
                example=item.get("example"),
            )
        )

    if not fields:
        raise ValueError("字段定义不能为空")

    return fields


def _build_generated_fields_table(fields: list[FieldDefinition]) -> Table:
    """构建字段预览表格。"""
    table = Table(title="AI 生成字段")
    table.add_column("name", style="cyan")
    table.add_column("description", style="green")
    table.add_column("type", style="magenta")
    table.add_column("required", style="yellow")
    table.add_column("example", style="blue")

    for field in fields:
        table.add_row(
            field.name,
            field.description,
            field.data_type,
            "是" if field.required else "否",
            field.example or "",
        )
    return table


def _load_urls(urls_file: str) -> list[str]:
    path = Path(urls_file)
    if not path.exists():
        raise ValueError(f"URL file not found: {urls_file}")

    content = path.read_text(encoding="utf-8")
    urls = [line.strip() for line in content.splitlines() if line.strip()]
    if not urls:
        raise ValueError("URL file is empty")
    return urls


def _serialize_fields(fields: list[FieldDefinition]) -> list[dict]:
    """将字段定义序列化为可传输字典。"""
    return [dataclasses.asdict(field) for field in fields]


def _log_graph_runtime(result: dict) -> None:
    """打印图运行时上下文。"""
    thread_id = str(result.get("thread_id") or "")
    checkpoint_id = str(result.get("checkpoint_id") or "")
    status = str(result.get("status") or "")

    if thread_id:
        message = f"[Graph] thread_id={thread_id}"
        if checkpoint_id:
            message += f", checkpoint_id={checkpoint_id}"
        message += f", status={status or 'unknown'}"
        logger.info(message)

    if status == "interrupted":
        interrupts = list(result.get("interrupts") or [])
        logger.info("[Graph] 执行已中断，可使用 `autospider resume --thread-id %s` 恢复", thread_id)
        for item in interrupts[:3]:
            logger.info("[Graph] interrupt %s: %s", item.get("id", ""), item.get("value"))


def _invoke_graph(entry_mode: str, cli_args: dict, *, thread_id: str = "") -> dict:
    """统一调用 GraphRunner 并返回 dict 结构结果。"""
    runner = GraphRunner()
    graph_input_kwargs = {
        "entry_mode": entry_mode,
        "cli_args": cli_args,
    }
    if thread_id:
        graph_input_kwargs["thread_id"] = thread_id
    graph_result = run_async_safely(runner.invoke(GraphInput(**graph_input_kwargs)))
    result = graph_result.model_dump()
    _log_graph_runtime(result)
    return result


def _parse_resume_payload(resume_json: str) -> tuple[object, bool]:
    """解析 CLI 输入的 resume payload。"""
    payload_text = str(resume_json or "").strip()
    if not payload_text:
        return None, False
    return json.loads(payload_text), True


def _resume_graph(
    thread_id: str,
    *,
    resume: object = None,
    use_command: bool = True,
    runner: GraphRunner | None = None,
) -> dict:
    """恢复图线程并返回 dict 结构结果。"""
    active_runner = runner or GraphRunner()
    graph_result = run_async_safely(
        active_runner.resume(
            thread_id=thread_id,
            resume=resume,
            use_command=use_command,
        )
    )
    result = graph_result.model_dump()
    _log_graph_runtime(result)
    return result



def _inspect_graph(thread_id: str, *, runner: GraphRunner | None = None) -> dict:
    """读取图线程当前状态。"""
    active_runner = runner or GraphRunner()
    graph_result = run_async_safely(active_runner.inspect(thread_id=thread_id))
    result = graph_result.model_dump()
    _log_graph_runtime(result)
    return result



def _primary_interrupt_payload(result: dict) -> dict[str, Any] | None:
    """提取首个 interrupt payload。"""
    for item in list(result.get("interrupts") or []):
        if not isinstance(item, dict):
            continue
        payload = item.get("value")
        if isinstance(payload, dict):
            return payload
    return None



def _field_definition_from_mapping(raw_field: dict[str, Any]) -> FieldDefinition:
    """将字典字段转换为 FieldDefinition。"""
    return FieldDefinition(
        name=str(raw_field.get("name") or ""),
        description=str(raw_field.get("description") or ""),
        required=bool(raw_field.get("required", True)),
        data_type=str(raw_field.get("data_type") or "text"),
        example=raw_field.get("example"),
    )



def _field_definitions_from_mappings(raw_fields: list[dict[str, Any]]) -> list[FieldDefinition]:
    """将字典字段列表转换为 FieldDefinition 列表。"""
    fields: list[FieldDefinition] = []
    for item in raw_fields:
        if not isinstance(item, dict):
            continue
        fields.append(_field_definition_from_mapping(item))
    return fields



def _edit_chat_review_task(task_payload: dict[str, Any]) -> dict[str, Any]:
    """交互式修改 review 阶段的字段。"""
    updated_task = dict(task_payload)
    fields = _field_definitions_from_mappings(list(updated_task.get("fields") or []))
    if not fields:
        raise ValueError("当前没有可编辑字段。")

    while True:
        console.print(_build_generated_fields_table(fields))
        index_text = typer.prompt(
            f"请输入要修改的字段序号（1-{len(fields)}），直接回车完成",
            default="",
        ).strip()
        if not index_text:
            break

        try:
            index = int(index_text)
        except ValueError as exc:
            raise ValueError("序号必须是数字。") from exc
        if index < 1 or index > len(fields):
            raise ValueError("序号超出范围。")

        selected = fields[index - 1]
        new_name = typer.prompt("字段 name", default=selected.name).strip() or selected.name
        new_desc = (
            typer.prompt("字段 description", default=selected.description).strip()
            or selected.description
        )
        new_type = (
            typer.prompt(
                "字段 type（text/number/date/url）",
                default=selected.data_type,
            )
            .strip()
            .lower()
        )
        if new_type not in {"text", "number", "date", "url"}:
            console.print("[yellow]字段 type 非法，已保留原值。[/yellow]")
            new_type = selected.data_type
        new_required = typer.confirm("是否必填（required）", default=selected.required)
        new_example = typer.prompt("字段 example（可空）", default=selected.example or "").strip()
        if not new_name or not new_desc:
            raise ValueError("name/description 不能为空。")

        fields[index - 1] = FieldDefinition(
            name=new_name,
            description=new_desc,
            required=new_required,
            data_type=new_type,
            example=new_example or None,
        )

        if not typer.confirm("继续修改其他字段？", default=False):
            break

    updated_task["fields"] = _serialize_fields(fields)
    return updated_task



def _handle_chat_clarification_interrupt(payload: dict[str, Any]) -> dict[str, Any]:
    """处理 chat 澄清 interrupt。"""
    question = str(payload.get("question") or "请补充更明确的采集目标、URL 或字段要求。")
    turn = payload.get("turn")
    max_turns = payload.get("max_turns")
    title = "AI 澄清问题"
    if turn and max_turns:
        title = f"AI 澄清问题 ({turn}/{max_turns})"
    console.print(Panel(question, title=title, style="yellow"))
    answer = typer.prompt("你的回答").strip()
    if not answer:
        answer = "请按常见默认方案继续，并明确你的默认假设。"
    return {"answer": answer}



def _handle_chat_review_interrupt(payload: dict[str, Any]) -> dict[str, Any]:
    """处理 chat review interrupt。"""
    task = dict(payload.get("clarified_task") or {})
    effective = dict(payload.get("effective_options") or {})
    fields = _field_definitions_from_mappings(list(task.get("fields") or []))
    mode_text = str(effective.get("pipeline_mode") or "默认")

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
            f"[bold]模式:[/bold] {mode_text}\n"
            f"[bold]执行引擎:[/bold] {effective.get('execution_mode') or 'multi'}\n"
            f"[bold]多任务并发:[/bold] {effective.get('max_concurrent') if effective.get('max_concurrent') is not None else '默认'}\n"
            f"[bold]无头模式:[/bold] {bool(effective.get('headless', False))}\n"
            f"[bold]输出目录:[/bold] {effective.get('output_dir') or 'output'}",
            title="AI 生成任务配置",
            style="cyan",
        )
    )
    if fields:
        console.print(_build_generated_fields_table(fields))

    while True:
        action = typer.prompt(
            "请选择下一步 [1=开始执行, 2=补充需求并重新生成, 3=手动修改字段后执行, 4=取消]",
            default="1",
        ).strip()
        if action == "1":
            return {"action": "approve"}
        if action == "2":
            supplement = typer.prompt(
                "请输入补充要求（示例：字段描述必须保留“相关统一交易标识码”）"
            ).strip()
            if not supplement:
                supplement = "请按常见默认方案继续，并明确你的默认假设。"
            return {"action": "supplement", "message": supplement}
        if action == "3":
            updated_task = _edit_chat_review_task(task)
            return {"action": "override_task", "task": updated_task}
        if action == "4":
            return {"action": "cancel"}
        console.print("[yellow]无效选项，请输入 1 / 2 / 3 / 4。[/yellow]")



def _handle_browser_intervention_interrupt(payload: dict[str, Any]) -> dict[str, Any]:
    """处理浏览器人工介入 interrupt。"""
    intervention_type = str(payload.get("intervention_type") or "browser_intervention")
    message = str(payload.get("message") or "请先处理浏览器中的异常，再继续恢复。")
    url = str(payload.get("url") or "")
    details = dict(payload.get("details") or {})

    extra_lines: list[str] = []
    if url:
        extra_lines.append(f"URL: {url}")
    auth_file = str(details.get("auth_file") or "")
    if auth_file:
        extra_lines.append(f"auth_file: {auth_file}")

    body = f"[yellow]{message}[/yellow]\n\nintervention_type: {intervention_type}"
    if extra_lines:
        body += "\n" + "\n".join(extra_lines)

    console.print(Panel(body, title="浏览器人工介入", style="yellow"))
    typer.confirm("处理完成后继续 resume？", default=True, abort=True)
    return {"action": "continue", "intervention_type": intervention_type}


def _continue_chat_interrupts(result: dict, *, runner: GraphRunner | None = None) -> dict:
    """在 CLI 中继续处理 chat-pipeline interrupt。"""
    active_runner = runner or GraphRunner()
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
        else:
            break

        thread_id = str(current.get("thread_id") or "")
        if not thread_id:
            break
        current = _resume_graph(
            thread_id,
            resume=resume_payload,
            use_command=True,
            runner=active_runner,
        )

    return current



def _print_graph_interrupted(result: dict) -> None:
    """打印仍处于中断状态的图结果。"""
    console.print(
        Panel(
            f"[yellow]线程仍处于中断状态[/yellow]\n\n"
            f"thread_id: {result.get('thread_id', '')}\n"
            f"interrupts: {json.dumps(list(result.get('interrupts') or []), ensure_ascii=False, indent=2)}",
            title="执行中断",
            style="yellow",
        )
    )



def _print_chat_pipeline_result(graph_result: dict, *, output_dir: str) -> None:
    """打印 chat-pipeline 执行结果。"""
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

def _raise_if_graph_failed(result: dict) -> None:
    """图执行失败时抛出可读异常。"""
    status = str(result.get("status") or "")
    if status != "failed":
        return
    error = result.get("error") or {}
    if isinstance(error, dict):
        message = str(error.get("message") or "图执行失败")
        code = str(error.get("code") or "")
        if code:
            raise RuntimeError(f"{code}: {message}")
        raise RuntimeError(message)
    raise RuntimeError("图执行失败")


@app.command("generate-config")
def generate_config_command(
    list_url: str = typer.Option(
        ...,
        "--list-url",
        "-u",
        help="列表页 URL",
    ),
    task: str = typer.Option(
        ...,
        "--task",
        "-t",
        help="任务描述（自然语言），例如：收集招标公告详情页",
    ),
    explore_count: int = typer.Option(
        3,
        "--explore-count",
        "-n",
        help="探索几个详情页来提取公共模式",
    ),
    headless: bool = typer.Option(
        False,
        "--headless/--no-headless",
        help="是否使用无头模式",
    ),
    output_dir: str = typer.Option(
        "output",
        "--output",
        "-o",
        help="输出目录",
    ),
    thread_id: str = typer.Option("", "--thread-id", help=_GRAPH_THREAD_ID_HELP),
):
    """
    生成爬取配置文件（第一阶段）

    探索网站并生成包含导航步骤、XPath 等信息的配置文件，
    配置文件可用于后续的批量收集。

    示例:
        autospider generate-config --list-url "https://example.com/list" --task "收集招标公告详情页"
    """
    # 显示配置
    logger.info(
        Panel(
            f"[bold]列表页 URL:[/bold] {list_url}\n"
            f"[bold]任务描述:[/bold] {task}\n"
            f"[bold]探索数量:[/bold] {explore_count} 个详情页\n"
            f"[bold]无头模式:[/bold] {headless}\n"
            f"[bold]输出目录:[/bold] {output_dir}",
            title="配置生成器",
            style="cyan",
        )
    )

    # 运行配置生成器
    try:
        graph_result = _invoke_graph(
            "generate_config",
            {
                "list_url": list_url,
                "task": task,
                "explore_count": explore_count,
                "headless": headless,
                "output_dir": output_dir,
            },
            thread_id=thread_id,
        )
        _raise_if_graph_failed(graph_result)
        summary = graph_result.get("summary") or {}

        # 显示结果
        logger.info(
            Panel(
                f"[green]配置文件已生成！[/green]\n\n"
                f"文件路径: {output_dir}/collection_config.json\n\n"
                f"配置内容:\n"
                f"  - 导航步骤: {summary.get('nav_steps', 0)} 个\n"
                f"  - 公共 XPath: {'已提取' if summary.get('has_common_detail_xpath') else '未提取'}\n"
                f"  - 分页控件: {'已提取' if summary.get('has_pagination_xpath') else '未提取'}\n"
                f"  - 跳转控件: {'已提取' if summary.get('has_jump_widget_xpath') else '未提取'}\n\n"
                f"下一步: 使用 'autospider batch-collect --config-path {output_dir}/collection_config.json' 进行批量收集",
                title="生成成功",
                style="green",
            )
        )

    except KeyboardInterrupt:
        logger.info("\n[yellow]用户中断[/yellow]")
        raise typer.Exit(130)
    except Exception as e:
        logger.info(
            Panel(
                f"[red]{str(e)}[/red]",
                title="执行错误",
                style="red",
            )
        )
        raise typer.Exit(1)


@app.command("batch-collect")
def batch_collect_command(
    config_path: str = typer.Option(
        ...,
        "--config-path",
        "-c",
        help="配置文件路径",
    ),
    max_pages: int | None = typer.Option(
        None,
        "--max-pages",
        help="最大翻页次数（覆盖配置）",
    ),
    target_url_count: int | None = typer.Option(
        None,
        "--target-url-count",
        help="目标采集 URL 数量（覆盖配置）",
    ),
    headless: bool = typer.Option(
        False,
        "--headless/--no-headless",
        help="是否使用无头模式",
    ),
    output_dir: str = typer.Option(
        "output",
        "--output",
        "-o",
        help="输出目录",
    ),
    thread_id: str = typer.Option("", "--thread-id", help=_GRAPH_THREAD_ID_HELP),
):
    """
    基于配置文件批量收集 URL（第二阶段）

    读取配置文件，执行批量 URL 收集，支持断点续爬。

    示例:
        autospider batch-collect --config-path output/collection_config.json
    """
    # 检查配置文件是否存在
    config_file = Path(config_path)
    if not config_file.exists():
        logger.info(
            Panel(
                f"[red]配置文件不存在: {config_path}[/red]\n\n"
                f"请先使用 'autospider generate-config' 生成配置文件",
                title="错误",
                style="red",
            )
        )
        raise typer.Exit(1)

    # 显示配置
    logger.info(
        Panel(
            f"[bold]配置文件:[/bold] {config_path}\n"
            f"[bold]最大翻页:[/bold] {max_pages if max_pages is not None else '默认'}\n"
            f"[bold]目标 URL 数:[/bold] {target_url_count if target_url_count is not None else '默认'}\n"
            f"[bold]无头模式:[/bold] {headless}\n"
            f"[bold]输出目录:[/bold] {output_dir}",
            title="批量收集器",
            style="cyan",
        )
    )

    # 运行批量收集器
    try:
        graph_result = _invoke_graph(
            "batch_collect",
            {
                "config_path": config_path,
                "max_pages": max_pages,
                "target_url_count": target_url_count,
                "headless": headless,
                "output_dir": output_dir,
            },
            thread_id=thread_id,
        )
        _raise_if_graph_failed(graph_result)
        result = (graph_result.get("data") or {}).get("result")

        # 显示结果
        collected_urls = list(getattr(result, "collected_urls", [])) if result else []
        logger.info(
            Panel(
                f"[green]共收集到 {len(collected_urls)} 个详情页 URL[/green]\n\n"
                f"结果已保存到:\n"
                f"  - {output_dir}/collected_urls.json\n"
                f"  - {output_dir}/urls.txt",
                title="收集完成",
                style="green",
            )
        )

        # 显示前 10 个 URL
        if collected_urls:
            logger.info("\n[bold]前 10 个 URL:[/bold]")
            for i, url in enumerate(collected_urls[:10], 1):
                logger.info(f"  {i}. {url}")
            if len(collected_urls) > 10:
                logger.info(f"  ... 还有 {len(collected_urls) - 10} 个")

    except KeyboardInterrupt:
        logger.info("\n[yellow]用户中断[/yellow]")
        raise typer.Exit(130)
    except Exception as e:
        logger.info(
            Panel(
                f"[red]{str(e)}[/red]",
                title="执行错误",
                style="red",
            )
        )
        raise typer.Exit(1)


@app.command("pipeline-run")
def pipeline_run_command(
    list_url: str = typer.Option(
        ...,
        "--list-url",
        "-u",
        help="列表页 URL",
    ),
    task: str = typer.Option(
        ...,
        "--task",
        "-t",
        help="任务描述（自然语言）",
    ),
    fields_json: str = typer.Option(
        "",
        "--fields-json",
        help="字段定义 JSON（数组格式）",
    ),
    fields_file: str = typer.Option(
        "",
        "--fields-file",
        help="字段定义 JSON 文件路径",
    ),
    field_explore_count: int | None = typer.Option(
        None,
        "--field-explore-count",
        help="字段探索数量（默认取配置）",
    ),
    field_validate_count: int | None = typer.Option(
        None,
        "--field-validate-count",
        help="字段校验数量（默认取配置）",
    ),
    max_pages: int | None = typer.Option(
        None,
        "--max-pages",
        help="列表页最大翻页次数（覆盖配置）",
    ),
    target_url_count: int | None = typer.Option(
        None,
        "--target-url-count",
        help="目标采集 URL 数量（覆盖配置）",
    ),
    consumer_concurrency: int | None = typer.Option(
        None,
        "--consumer-concurrency",
        help="详情抽取消费者并发数（默认取配置）",
    ),
    pipeline_mode: str = typer.Option(
        "",
        "--mode",
        help="通道模式: memory/file/redis",
    ),
    headless: bool = typer.Option(
        False,
        "--headless/--no-headless",
        help="是否使用无头模式",
    ),
    output_dir: str = typer.Option(
        "output",
        "--output",
        "-o",
        help="输出目录",
    ),
    thread_id: str = typer.Option("", "--thread-id", help=_GRAPH_THREAD_ID_HELP),
):
    """列表采集与详情抽取并行流水线。"""
    try:
        list_url = validate_url(list_url)
        task = validate_task_description(task)
        fields = _load_fields(fields_json, fields_file)
    except (URLValidationError, ValidationError, ValueError) as e:
        logger.info(
            Panel(
                f"[red]{str(e)}[/red]",
                title="输入验证错误",
                style="red",
            )
        )
        raise typer.Exit(1)

    mode_text = pipeline_mode.strip() if pipeline_mode else "默认"
    logger.info(
        Panel(
            f"[bold]列表页 URL:[/bold] {list_url}\n"
            f"[bold]任务描述:[/bold] {task}\n"
            f"[bold]字段数量:[/bold] {len(fields)}\n"
            f"[bold]最大翻页:[/bold] {max_pages if max_pages is not None else '默认'}\n"
            f"[bold]目标 URL 数:[/bold] {target_url_count if target_url_count is not None else '默认'}\n"
            f"[bold]消费者并发:[/bold] {consumer_concurrency if consumer_concurrency is not None else '默认'}\n"
            f"[bold]模式:[/bold] {mode_text}\n"
            f"[bold]无头模式:[/bold] {headless}\n"
            f"[bold]输出目录:[/bold] {output_dir}",
            title="流水线配置",
            style="cyan",
        )
    )

    try:
        graph_result = _invoke_graph(
            "pipeline_run",
            {
                "list_url": list_url,
                "task_description": task,
                "fields": _serialize_fields(fields),
                "output_dir": output_dir,
                "headless": headless,
                "field_explore_count": field_explore_count,
                "field_validate_count": field_validate_count,
                "consumer_concurrency": consumer_concurrency,
                "max_pages": max_pages,
                "target_url_count": target_url_count,
                "pipeline_mode": pipeline_mode.strip() or None,
            },
            thread_id=thread_id,
        )
        _raise_if_graph_failed(graph_result)
        result = (graph_result.get("data") or {}).get("result") or {}

        logger.info(
            Panel(
                f"[green]流水线完成[/green]\n\n"
                f"总处理 URL: {result.get('total_urls', 0)}\n"
                f"成功数量: {result.get('success_count', 0)}\n"
                f"明细输出: {result.get('items_file', '')}\n"
                f"汇总输出: {output_dir}/pipeline_summary.json",
                title="执行完成",
                style="green",
            )
        )
    except KeyboardInterrupt:
        logger.info("\n[yellow]用户中断[/yellow]")
        raise typer.Exit(130)
    except Exception as e:
        logger.info(
            Panel(
                f"[red]{str(e)}[/red]",
                title="执行错误",
                style="red",
            )
        )
        raise typer.Exit(1)


@app.command("chat-pipeline")
def chat_pipeline_command(
    request: str = typer.Option(
        "",
        "--request",
        "-r",
        help="初始自然语言需求（可为空，程序会交互询问）",
    ),
    max_turns: int = typer.Option(
        6,
        "--max-turns",
        help="多轮澄清的最大轮数",
    ),
    field_explore_count: int | None = typer.Option(
        None,
        "--field-explore-count",
        help="字段探索数量（默认取配置）",
    ),
    field_validate_count: int | None = typer.Option(
        None,
        "--field-validate-count",
        help="字段校验数量（默认取配置）",
    ),
    max_pages: int | None = typer.Option(
        None,
        "--max-pages",
        help="列表页最大翻页次数（可覆盖 AI 推断）",
    ),
    target_url_count: int | None = typer.Option(
        None,
        "--target-url-count",
        help="目标采集 URL 数量（可覆盖 AI 推断）",
    ),
    consumer_concurrency: int | None = typer.Option(
        None,
        "--consumer-concurrency",
        help="详情抽取消费者并发数（默认取配置）",
    ),
    pipeline_mode: str = typer.Option(
        "",
        "--mode",
        help="通道模式: memory/file/redis",
    ),
    max_concurrent: int | None = typer.Option(
        None,
        "--max-concurrent",
        help="多分类子任务最大并发数（用于 multi）",
    ),
    headless: bool = typer.Option(
        False,
        "--headless/--no-headless",
        help="是否使用无头模式",
    ),
    output_dir: str = typer.Option(
        "output",
        "--output",
        "-o",
        help="输出目录",
    ),
    thread_id: str = typer.Option("", "--thread-id", help=_GRAPH_THREAD_ID_HELP),
):
    """全自然语言多轮交互后执行流水线。"""
    if max_turns < 1:
        console.print(
            Panel(
                "[red]max-turns 必须 >= 1[/red]",
                title="参数错误",
                style="red",
            )
        )
        raise typer.Exit(1)

    initial_request = request.strip()
    if not initial_request:
        initial_request = typer.prompt("请描述你想爬取什么（可模糊）").strip()

    if not initial_request:
        console.print(
            Panel(
                "[red]需求不能为空[/red]",
                title="输入错误",
                style="red",
            )
        )
        raise typer.Exit(1)

    try:
        graph_result = _invoke_graph(
            "chat_pipeline",
            {
                "request": initial_request,
                "max_turns": max_turns,
                "headless": headless,
                "output_dir": output_dir,
                "max_pages": max_pages,
                "target_url_count": target_url_count,
                "consumer_concurrency": consumer_concurrency,
                "field_explore_count": field_explore_count,
                "field_validate_count": field_validate_count,
                "pipeline_mode": pipeline_mode.strip() or None,
                "max_concurrent": max_concurrent,
            },
            thread_id=thread_id,
        )
        graph_result = _continue_chat_interrupts(graph_result)
        _raise_if_graph_failed(graph_result)
        if str(graph_result.get("status") or "") == "interrupted":
            _print_graph_interrupted(graph_result)
            return
        _print_chat_pipeline_result(graph_result, output_dir=output_dir)
    except KeyboardInterrupt:
        logger.info("\n[yellow]用户中断[/yellow]")
        raise typer.Exit(130)
    except Exception as e:
        console.print(
            Panel(
                f"[red]{str(e)}[/red]",
                title="执行错误",
                style="red",
            )
        )
        raise typer.Exit(1)




@app.command("field-extract")
def field_extract_command(
    urls_file: str = typer.Option(
        ..., "--urls-file", help="URL list file (one URL per line)"
    ),
    fields_json: str = typer.Option(
        "", "--fields-json", help="Fields JSON definition (array)"
    ),
    fields_file: str = typer.Option(
        "", "--fields-file", help="Fields JSON file path"
    ),
    field_explore_count: int | None = typer.Option(
        None, "--field-explore-count", help="Explore count for field extraction"
    ),
    field_validate_count: int | None = typer.Option(
        None, "--field-validate-count", help="Validate count for field extraction"
    ),
    headless: bool = typer.Option(
        False, "--headless/--no-headless", help="Run browser in headless mode"
    ),
    output_dir: str = typer.Option(
        "output", "--output", "-o", help="Output directory"
    ),
    thread_id: str = typer.Option("", "--thread-id", help=_GRAPH_THREAD_ID_HELP),
):
    """Field extraction pipeline (explore + XPath batch)."""
    try:
        urls = _load_urls(urls_file)
        fields = _load_fields(fields_json, fields_file)
    except (URLValidationError, ValidationError, ValueError) as e:
        logger.info(
            Panel(
                f"[red]{str(e)}[/red]",
                title="Input error",
                style="red",
            )
        )
        raise typer.Exit(1)

    logger.info(
        Panel(
            f"[bold]URL count:[/bold] {len(urls)}\n"
            f"[bold]Field count:[/bold] {len(fields)}\n"
            f"[bold]Headless:[/bold] {headless}\n"
            f"[bold]Output:[/bold] {output_dir}",
            title="Field extraction",
            style="cyan",
        )
    )

    try:
        graph_result = _invoke_graph(
            "field_extract",
            {
                "urls": urls,
                "fields": _serialize_fields(fields),
                "output_dir": output_dir,
                "headless": headless,
                "field_explore_count": field_explore_count,
                "field_validate_count": field_validate_count,
            },
            thread_id=thread_id,
        )
        _raise_if_graph_failed(graph_result)

        logger.info(
            Panel(
                f"[green]Field extraction finished[/green]\n\n"
                f"Config: {output_dir}/extraction_config.json\n"
                f"Explore: {output_dir}/extraction_result.json\n"
                f"Items: {output_dir}/extracted_items.json",
                title="Done",
                style="green",
            )
        )
    except KeyboardInterrupt:
        logger.info("\n[yellow]Interrupted[/yellow]")
        raise typer.Exit(130)
    except Exception as e:
        logger.info(
            Panel(
                f"[red]{str(e)}[/red]",
                title="Execution error",
                style="red",
            )
        )
        raise typer.Exit(1)


@app.command("collect-urls")
def collect_urls_command(
    list_url: str = typer.Option(
        ...,
        "--list-url",
        "-u",
        help="列表页 URL",
    ),
    task: str = typer.Option(
        ...,
        "--task",
        "-t",
        help="任务描述（自然语言），例如：收集招标公告详情页",
    ),
    explore_count: int = typer.Option(
        3,
        "--explore-count",
        "-n",
        help="探索几个详情页来提取公共模式",
    ),
    max_pages: int | None = typer.Option(
        None,
        "--max-pages",
        help="最大翻页次数（覆盖配置）",
    ),
    target_url_count: int | None = typer.Option(
        None,
        "--target-url-count",
        help="目标采集 URL 数量（覆盖配置）",
    ),
    headless: bool = typer.Option(
        False,
        "--headless/--no-headless",
        help="是否使用无头模式",
    ),
    output_dir: str = typer.Option(
        "output",
        "--output",
        "-o",
        help="输出目录",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="预览模式，只验证参数不实际执行",
    ),
    thread_id: str = typer.Option("", "--thread-id", help=_GRAPH_THREAD_ID_HELP),
):
    """
    收集详情页 URL

    流程:
    1. LLM 根据你的任务描述，识别列表页中的目标详情链接
    2. 进入 N 个不同的详情页，记录进入方式
    3. 分析这 N 次操作的共同模式，提取公共脚本
    4. 使用公共脚本遍历列表页，收集所有详情页 URL

    示例:
        autospider collect-urls --list-url "https://example.com/list" --task "收集招标公告详情页" --explore-count 3
    """
    # 输入验证
    try:
        list_url = validate_url(list_url)
        task = validate_task_description(task)
    except (URLValidationError, ValidationError) as e:
        logger.info(
            Panel(
                f"[red]{str(e)}[/red]",
                title="输入验证错误",
                style="red",
            )
        )
        raise typer.Exit(1)

    # 显示配置
    logger.info(
        Panel(
            f"[bold]列表页 URL:[/bold] {list_url}\n"
            f"[bold]任务描述:[/bold] {task}\n"
            f"[bold]探索数量:[/bold] {explore_count} 个详情页\n"
            f"[bold]最大翻页:[/bold] {max_pages if max_pages is not None else '默认'}\n"
            f"[bold]目标 URL 数:[/bold] {target_url_count if target_url_count is not None else '默认'}\n"
            f"[bold]无头模式:[/bold] {headless}\n"
            f"[bold]输出目录:[/bold] {output_dir}"
            + (
                "\n[bold yellow]模式:[/bold yellow] [yellow]预览模式 (dry-run)[/yellow]"
                if dry_run
                else ""
            ),
            title="URL 收集器配置",
            style="cyan",
        )
    )

    # Dry-run 模式：只验证参数，不实际执行
    if dry_run:
        logger.info(
            Panel(
                "[green]✓ 参数验证通过[/green]\n\n"
                "将执行以下操作：\n"
                f"  1. 打开浏览器访问 {list_url}\n"
                f"  2. 探索 {explore_count} 个详情页提取模式\n"
                f"  3. 收集详情页 URL 并保存到 {output_dir}/\n"
                f"  4. 生成爬虫脚本 {output_dir}/spider.py\n\n"
                "使用 [cyan]--no-dry-run[/cyan] 或移除 [cyan]--dry-run[/cyan] 执行实际操作",
                title="预览完成",
                style="green",
            )
        )
        return

    # 运行收集器（状态提示）
    try:
        with console.status("[cyan]正在执行收集任务...[/cyan]", spinner="dots"):
            graph_result = _invoke_graph(
                "collect_urls",
                {
                    "list_url": list_url,
                    "task": task,
                    "explore_count": explore_count,
                    "max_pages": max_pages,
                    "target_url_count": target_url_count,
                    "headless": headless,
                    "output_dir": output_dir,
                },
                thread_id=thread_id,
            )
            _raise_if_graph_failed(graph_result)
            result = (graph_result.get("data") or {}).get("result")

        # 显示结果
        logger.info("\n")

        # 显示探索的详情页
        if result and result.detail_visits:
            table = Table(title="探索的详情页")
            table.add_column("序号", style="cyan")
            table.add_column("元素文本", style="green")
            table.add_column("详情页 URL", style="blue")

            for i, visit in enumerate(result.detail_visits, 1):
                table.add_row(
                    str(i),
                    (
                        visit.clicked_element_text[:30] + "..."
                        if len(visit.clicked_element_text) > 30
                        else visit.clicked_element_text
                    ),
                    (
                        visit.detail_page_url[:60] + "..."
                        if len(visit.detail_page_url) > 60
                        else visit.detail_page_url
                    ),
                )
            logger.info(table)

        # 显示提取的模式
        if result and result.common_pattern:
            pattern = result.common_pattern
            logger.info(
                Panel(
                    f"[bold]标签模式:[/bold] {pattern.tag_pattern or '无'}\n"
                    f"[bold]角色模式:[/bold] {pattern.role_pattern or '无'}\n"
                    f"[bold]链接模式:[/bold] {pattern.href_pattern or '无'}\n"
                    f"[bold]XPath 模式:[/bold] {pattern.xpath_pattern or '无'}\n"
                    f"[bold]置信度:[/bold] {pattern.confidence:.1%}",
                    title="提取的公共模式",
                    style="magenta",
                )
            )

        # 显示收集结果
        collected_urls = list(getattr(result, "collected_urls", [])) if result else []
        logger.info(
            Panel(
                f"[green]共收集到 {len(collected_urls)} 个详情页 URL[/green]\n\n"
                f"结果已保存到:\n"
                f"  - {output_dir}/collected_urls.json\n"
                f"  - {output_dir}/urls.txt",
                title="收集完成",
                style="green",
            )
        )

        # 显示前 10 个 URL
        if collected_urls:
            logger.info("\n[bold]前 10 个 URL:[/bold]")
            for i, url in enumerate(collected_urls[:10], 1):
                logger.info(f"  {i}. {url}")
            if len(collected_urls) > 10:
                logger.info(f"  ... 还有 {len(collected_urls) - 10} 个")

    except KeyboardInterrupt:
        logger.info("\n[yellow]用户中断[/yellow]")
        raise typer.Exit(130)
    except Exception as e:
        logger.info(
            Panel(
                f"[red]{str(e)}[/red]",
                title="执行错误",
                style="red",
            )
        )
        raise typer.Exit(1)


def main():
    """CLI 入口点

    供 pyproject.toml 中 [project.scripts] 调用。
    """
    app()


@app.command("multi-pipeline")
def multi_pipeline_command(
    site_url: str = typer.Option(
        ...,
        "--site-url",
        "-u",
        help="目标网站 URL（首页或列表页入口）",
    ),
    request: str = typer.Option(
        "",
        "--request",
        "-r",
        help="自然语言采集需求，如：爬取全站所有分类的数据",
    ),
    fields_json: str = typer.Option(
        "",
        "--fields-json",
        help="字段定义 JSON（数组格式）",
    ),
    fields_file: str = typer.Option(
        "",
        "--fields-file",
        help="字段定义 JSON 文件路径",
    ),
    max_concurrent: int | None = typer.Option(
        None,
        "--max-concurrent",
        help="子任务最大并发数（默认取配置）",
    ),
    headless: bool = typer.Option(
        False,
        "--headless/--no-headless",
        help="是否使用无头模式",
    ),
    output_dir: str = typer.Option(
        "output",
        "--output",
        "-o",
        help="输出目录",
    ),
    thread_id: str = typer.Option("", "--thread-id", help=_GRAPH_THREAD_ID_HELP),
):
    """多分类并行采集流水线（Plan-Execute 架构）。

    自动分析网站结构，将大任务拆分为多个子任务并行执行。

    示例:
        autospider multi-pipeline --site-url "https://example.com" --request "爬取全站所有分类的数据" --fields-file fields.json
    """
    if not request:
        request = typer.prompt("请描述你的采集需求（如：爬取全站所有分类的数据）").strip()
    if not request:
        console.print(Panel("[red]需求不能为空[/red]", title="输入错误", style="red"))
        raise typer.Exit(1)

    try:
        site_url = validate_url(site_url)
    except (URLValidationError, ValidationError, ValueError) as e:
        console.print(Panel(f"[red]{str(e)}[/red]", title="URL 验证错误", style="red"))
        raise typer.Exit(1)

    # 加载字段定义（可选）
    import dataclasses
    fields_dicts: list[dict] = []
    if fields_json or fields_file:
        try:
            loaded = _load_fields(fields_json, fields_file)
            fields_dicts = [dataclasses.asdict(f) for f in loaded]
        except Exception as e:
            console.print(Panel(f"[red]{str(e)}[/red]", title="字段加载错误", style="red"))
            raise typer.Exit(1)

    console.print(
        Panel(
            f"[bold]目标网站:[/bold] {site_url}\n"
            f"[bold]采集需求:[/bold] {request}\n"
            f"[bold]字段数量:[/bold] {len(fields_dicts) if fields_dicts else '待定'}\n"
            f"[bold]最大并发:[/bold] {max_concurrent if max_concurrent else '默认'}\n"
            f"[bold]无头模式:[/bold] {headless}\n"
            f"[bold]输出目录:[/bold] {output_dir}",
            title="多分类并行采集",
            style="cyan",
        )
    )

    try:
        graph_result = _invoke_graph(
            "multi_pipeline",
            {
                "site_url": site_url,
                "request": request,
                "fields": fields_dicts,
                "max_concurrent": max_concurrent,
                "headless": headless,
                "output_dir": output_dir,
            },
            thread_id=thread_id,
        )
        _raise_if_graph_failed(graph_result)
        result = graph_result.get("summary") or {}

        console.print(
            Panel(
                f"[green]多分类采集完成[/green]\n\n"
                f"总子任务数: {result.get('total', 0)}\n"
                f"成功: {result.get('completed', 0)}\n"
                f"失败: {result.get('failed', 0)}\n"
                f"总采集数: {result.get('total_collected', 0)}\n"
                f"合并结果: {output_dir}/merged_results.jsonl\n"
                f"恢复线程: {result.get('thread_id') or graph_result.get('thread_id', '')}",
                title="执行完成",
                style="green",
            )
        )

    except KeyboardInterrupt:
        logger.info("\n[yellow]用户中断[/yellow]")
        raise typer.Exit(130)
    except typer.Exit:
        raise
    except Exception as e:
        console.print(Panel(f"[red]{str(e)}[/red]", title="执行错误", style="red"))
        raise typer.Exit(1)



@app.command("resume")
def resume_graph_command(
    thread_id: str = typer.Option(..., "--thread-id", help="需要恢复的 LangGraph 线程 ID"),
    resume_json: str = typer.Option(
        "",
        "--resume-json",
        help="interrupt 恢复载荷（JSON）。留空时按静态断点继续。",
    ),
):
    """恢复已持久化的 LangGraph 线程。"""
    try:
        resume_payload, has_payload = _parse_resume_payload(resume_json)
        runner = GraphRunner()
        if has_payload:
            result = _resume_graph(
                thread_id,
                resume=resume_payload,
                use_command=True,
                runner=runner,
            )
        else:
            current_state = _inspect_graph(thread_id, runner=runner)
            if str(current_state.get("status") or "") == "interrupted":
                result = _continue_chat_interrupts(current_state, runner=runner)
            elif list(current_state.get("next_nodes") or []):
                result = _resume_graph(
                    thread_id,
                    resume=None,
                    use_command=False,
                    runner=runner,
                )
            else:
                result = current_state

        if str(result.get("status") or "") == "interrupted":
            result = _continue_chat_interrupts(result, runner=runner)

        _raise_if_graph_failed(result)

        status = str(result.get("status") or "")
        summary = result.get("summary") or {}
        if status == "interrupted":
            _print_graph_interrupted(result)
            return

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
        logger.info("\n[yellow]用户中断[/yellow]")
        raise typer.Exit(130)
    except json.JSONDecodeError as exc:
        console.print(Panel(f"[red]resume-json 不是合法 JSON: {exc}[/red]", title="输入错误", style="red"))
        raise typer.Exit(1)
    except Exception as exc:
        console.print(Panel(f"[red]{str(exc)}[/red]", title="恢复失败", style="red"))
        raise typer.Exit(1)

if __name__ == "__main__":
    main()
