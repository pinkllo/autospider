"""CLI 入口"""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .common.browser import create_browser_session
from .common.validators import validate_url, validate_task_description
from .common.exceptions import ValidationError, URLValidationError
from .common.llm import TaskClarifier, DialogueMessage
from .common.logger import get_logger
from .field import FieldDefinition
from .pipeline import run_pipeline
from .field import run_field_pipeline

# 日志器
logger = get_logger(__name__)

app = typer.Typer(
    name="autospider",
    help="AutoSpider CLI - 采集与配置工具",
    add_completion=False,
)
console = Console()


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


def _load_generated_fields(generated_fields: list[FieldDefinition]) -> list[FieldDefinition]:
    """校验 AI 生成字段列表。"""
    if not generated_fields:
        raise ValueError("AI 未生成有效字段，请补充更具体的字段要求")
    return generated_fields


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
        result = run_async_safely(
            _run_config_generator(
                list_url=list_url,
                task=task,
                explore_count=explore_count,
                headless=headless,
                output_dir=output_dir,
            )
        )

        # 显示结果
        logger.info(
            Panel(
                f"[green]配置文件已生成！[/green]\n\n"
                f"文件路径: {output_dir}/collection_config.json\n\n"
                f"配置内容:\n"
                f"  - 导航步骤: {len(result.nav_steps)} 个\n"
                f"  - 公共 XPath: {'已提取' if result.common_detail_xpath else '未提取'}\n"
                f"  - 分页控件: {'已提取' if result.pagination_xpath else '未提取'}\n"
                f"  - 跳转控件: {'已提取' if result.jump_widget_xpath else '未提取'}\n\n"
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
            f"[bold]无头模式:[/bold] {headless}\n"
            f"[bold]输出目录:[/bold] {output_dir}",
            title="批量收集器",
            style="cyan",
        )
    )

    # 运行批量收集器
    try:
        result = run_async_safely(
            _run_batch_collector(
                config_path=config_path,
                max_pages=max_pages,
                headless=headless,
                output_dir=output_dir,
            )
        )

        # 显示结果
        logger.info(
            Panel(
                f"[green]共收集到 {len(result.collected_urls)} 个详情页 URL[/green]\n\n"
                f"结果已保存到:\n"
                f"  - {output_dir}/collected_urls.json\n"
                f"  - {output_dir}/urls.txt",
                title="收集完成",
                style="green",
            )
        )

        # 显示前 10 个 URL
        if result.collected_urls:
            logger.info("\n[bold]前 10 个 URL:[/bold]")
            for i, url in enumerate(result.collected_urls[:10], 1):
                logger.info(f"  {i}. {url}")
            if len(result.collected_urls) > 10:
                logger.info(f"  ... 还有 {len(result.collected_urls) - 10} 个")

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
        result = run_async_safely(
            run_pipeline(
                list_url=list_url,
                task_description=task,
                fields=fields,
                output_dir=output_dir,
                headless=headless,
                explore_count=field_explore_count,
                validate_count=field_validate_count,
                consumer_concurrency=consumer_concurrency,
                max_pages=max_pages,
                target_url_count=target_url_count,
                pipeline_mode=pipeline_mode.strip() or None,
            )
        )

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
        clarifier = TaskClarifier()
    except Exception as e:
        console.print(
            Panel(
                f"[red]澄清器初始化失败: {str(e)}[/red]",
                title="执行错误",
                style="red",
            )
        )
        raise typer.Exit(1)

    history: list[DialogueMessage] = [DialogueMessage(role="user", content=initial_request)]
    final_task = None

    for turn in range(1, max_turns + 1):
        result = run_async_safely(clarifier.clarify(history))

        if result.status == "reject":
            console.print(
                Panel(
                    f"[red]{result.reason or '该任务暂不支持自动执行'}[/red]",
                    title="任务拒绝",
                    style="red",
                )
            )
            raise typer.Exit(1)

        if result.status == "ready" and result.task is not None:
            final_task = result.task
            break

        question = result.next_question or "请补充更明确的采集目标、URL 或字段要求。"
        console.print(
            Panel(
                question,
                title=f"AI 澄清问题 ({turn}/{max_turns})",
                style="yellow",
            )
        )
        answer = typer.prompt("你的回答").strip()
        if not answer:
            answer = "请按常见默认方案继续，并明确你的默认假设。"

        history.append(DialogueMessage(role="assistant", content=question))
        history.append(DialogueMessage(role="user", content=answer))

    if final_task is None:
        console.print(
            Panel(
                "[red]在限定轮数内仍未澄清完成。请提供更明确的信息后重试。[/red]",
                title="澄清未完成",
                style="red",
            )
        )
        raise typer.Exit(1)

    try:
        list_url = validate_url(final_task.list_url)
        task_description = validate_task_description(final_task.task_description)
        fields = _load_generated_fields(final_task.fields)
    except (URLValidationError, ValidationError, ValueError) as e:
        console.print(
            Panel(
                f"[red]{str(e)}[/red]",
                title="AI 结果校验失败",
                style="red",
            )
        )
        raise typer.Exit(1)

    use_max_pages = max_pages if max_pages is not None else final_task.max_pages
    use_target_url_count = (
        target_url_count
        if target_url_count is not None
        else final_task.target_url_count
    )
    use_consumer_concurrency = (
        consumer_concurrency
        if consumer_concurrency is not None
        else final_task.consumer_concurrency
    )
    use_field_explore_count = (
        field_explore_count
        if field_explore_count is not None
        else final_task.field_explore_count
    )
    use_field_validate_count = (
        field_validate_count
        if field_validate_count is not None
        else final_task.field_validate_count
    )
    mode_text = pipeline_mode.strip() if pipeline_mode else "默认"
    intent_text = final_task.intent or "未提供"

    console.print(
        Panel(
            f"[bold]识别意图:[/bold] {intent_text}\n"
            f"[bold]列表页 URL:[/bold] {list_url}\n"
            f"[bold]任务描述:[/bold] {task_description}\n"
            f"[bold]字段数量:[/bold] {len(fields)}\n"
            f"[bold]最大翻页:[/bold] {use_max_pages if use_max_pages is not None else '默认'}\n"
            f"[bold]目标 URL 数:[/bold] "
            f"{use_target_url_count if use_target_url_count is not None else '默认'}\n"
            f"[bold]字段探索数:[/bold] "
            f"{use_field_explore_count if use_field_explore_count is not None else '默认'}\n"
            f"[bold]字段校验数:[/bold] "
            f"{use_field_validate_count if use_field_validate_count is not None else '默认'}\n"
            f"[bold]消费者并发:[/bold] "
            f"{use_consumer_concurrency if use_consumer_concurrency is not None else '默认'}\n"
            f"[bold]模式:[/bold] {mode_text}\n"
            f"[bold]无头模式:[/bold] {headless}\n"
            f"[bold]输出目录:[/bold] {output_dir}",
            title="AI 生成任务配置",
            style="cyan",
        )
    )
    console.print(_build_generated_fields_table(fields))

    if not typer.confirm("是否确认并开始执行流水线？", default=True):
        logger.info("[yellow]已取消执行[/yellow]")
        return

    try:
        run_result = run_async_safely(
            run_pipeline(
                list_url=list_url,
                task_description=task_description,
                fields=fields,
                output_dir=output_dir,
                headless=headless,
                explore_count=use_field_explore_count,
                validate_count=use_field_validate_count,
                consumer_concurrency=use_consumer_concurrency,
                max_pages=use_max_pages,
                target_url_count=use_target_url_count,
                pipeline_mode=pipeline_mode.strip() or None,
            )
        )

        console.print(
            Panel(
                f"[green]流水线完成[/green]\n\n"
                f"总处理 URL: {run_result.get('total_urls', 0)}\n"
                f"成功数量: {run_result.get('success_count', 0)}\n"
                f"明细输出: {run_result.get('items_file', '')}\n"
                f"汇总输出: {output_dir}/pipeline_summary.json",
                title="执行完成",
                style="green",
            )
        )
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
        run_async_safely(
            _run_field_pipeline(
                urls=urls,
                fields=fields,
                output_dir=output_dir,
                headless=headless,
                explore_count=field_explore_count,
                validate_count=field_validate_count,
            )
        )

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


async def _run_field_pipeline(
    urls: list[str],
    fields: list[FieldDefinition],
    output_dir: str,
    headless: bool,
    explore_count: int | None,
    validate_count: int | None,
):
    from .common.config import config

    use_explore = explore_count if explore_count is not None else config.field_extractor.explore_count
    use_validate = validate_count if validate_count is not None else config.field_extractor.validate_count

    async with create_browser_session(headless=headless, close_engine=True) as session:
        return await run_field_pipeline(
            page=session.page,
            urls=urls,
            fields=fields,
            output_dir=output_dir,
            explore_count=use_explore,
            validate_count=use_validate,
            run_xpath=True,
        )

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
            result = run_async_safely(
                _run_collector(
                    list_url=list_url,
                    task=task,
                    explore_count=explore_count,
                    max_pages=max_pages,
                    headless=headless,
                    output_dir=output_dir,
                )
            )

        # 显示结果
        logger.info("\n")

        # 显示探索的详情页
        if result.detail_visits:
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
        if result.common_pattern:
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
        logger.info(
            Panel(
                f"[green]共收集到 {len(result.collected_urls)} 个详情页 URL[/green]\n\n"
                f"结果已保存到:\n"
                f"  - {output_dir}/collected_urls.json\n"
                f"  - {output_dir}/urls.txt",
                title="收集完成",
                style="green",
            )
        )

        # 显示前 10 个 URL
        if result.collected_urls:
            logger.info("\n[bold]前 10 个 URL:[/bold]")
            for i, url in enumerate(result.collected_urls[:10], 1):
                logger.info(f"  {i}. {url}")
            if len(result.collected_urls) > 10:
                logger.info(f"  ... 还有 {len(result.collected_urls) - 10} 个")

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


async def _run_config_generator(
    list_url: str,
    task: str,
    explore_count: int,
    headless: bool,
    output_dir: str,
):
    """异步运行配置生成器"""
    from .crawler.explore.config_generator import generate_collection_config

    session = None
    try:
        async with create_browser_session(headless=headless, close_engine=True) as session:
            return await generate_collection_config(
                page=session.page,
                list_url=list_url,
                task_description=task,
                explore_count=explore_count,
                output_dir=output_dir,
            )
    except (KeyboardInterrupt, asyncio.CancelledError):
        # 确保浏览器会话被正确清理
        if session:
            try:
                await session.stop()
            except Exception:
                pass
        raise KeyboardInterrupt("用户中断")


async def _run_batch_collector(
    config_path: str,
    max_pages: int | None,
    headless: bool,
    output_dir: str,
):
    """异步运行批量收集器"""
    from .crawler.batch.batch_collector import batch_collect_urls
    from .common.config import config

    previous_max_pages: int | None = None
    if max_pages is not None:
        previous_max_pages = config.url_collector.max_pages
        config.url_collector.max_pages = int(max_pages)

    try:
        async with create_browser_session(headless=headless, close_engine=True) as session:
            return await batch_collect_urls(
                page=session.page,
                config_path=config_path,
                output_dir=output_dir,
            )
    finally:
        if previous_max_pages is not None:
            config.url_collector.max_pages = previous_max_pages


async def _run_collector(
    list_url: str,
    task: str,
    explore_count: int,
    max_pages: int | None,
    headless: bool,
    output_dir: str,
):
    """异步运行 URL 收集器（完整流程）"""
    from .crawler.explore.url_collector import collect_detail_urls
    from .common.config import config

    previous_max_pages: int | None = None
    if max_pages is not None:
        previous_max_pages = config.url_collector.max_pages
        config.url_collector.max_pages = int(max_pages)

    try:
        async with create_browser_session(headless=headless, close_engine=True) as session:
            return await collect_detail_urls(
                page=session.page,
                list_url=list_url,
                task_description=task,
                explore_count=explore_count,
                output_dir=output_dir,
            )
    finally:
        if previous_max_pages is not None:
            config.url_collector.max_pages = previous_max_pages


def main():
    """CLI 入口点

    供 pyproject.toml 中 [project.scripts] 调用。
    """
    app()


if __name__ == "__main__":
    main()
