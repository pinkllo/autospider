"""CLI 入口"""

from __future__ import annotations

import asyncio
import threading
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table

from .common.browser import create_browser_session
from .common.config import config
from .common.validators import validate_url, validate_task_description
from .common.exceptions import ValidationError, URLValidationError
from .common.logger import get_logger
from .extractor.graph import run_agent
from .common.types import RunInput

# 日志器
logger = get_logger(__name__)

app = typer.Typer(
    name="autospider",
    help="纯视觉 SoM 浏览器 Agent - 使用 LangGraph + 多模态 LLM",
    add_completion=False,
)
console = Console()


def run_async_safely(coro):
    """在 CLI 同步上下文中安全执行协程。"""
    # 修改原因：CLI 中直接调用 run_async_safely，但此前未定义该方法会抛 NameError。
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result_holder: dict[str, object] = {"result": None, "error": None}

    def _runner():
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            result_holder["result"] = loop.run_until_complete(coro)
        except Exception as exc:  # noqa: BLE001
            result_holder["error"] = exc
        finally:
            loop.close()
            asyncio.set_event_loop(None)

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()

    if result_holder["error"] is not None:
        raise result_holder["error"]  # type: ignore[misc]
    return result_holder["result"]


@app.command("run")
def run_command(
    start_url: str = typer.Option(
        ...,
        "--start-url",
        "-u",
        help="起始 URL",
    ),
    task: str = typer.Option(
        ...,
        "--task",
        "-t",
        help="任务描述（自然语言）",
    ),
    target_text: str = typer.Option(
        ...,
        "--target-text",
        "-x",
        help="提取目标文本",
    ),
    max_steps: int = typer.Option(
        20,
        "--max-steps",
        "-s",
        help="最大执行步数",
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
    运行纯视觉 SoM 浏览器 Agent
    
    示例:
        autospider run --start-url "https://example.com" --task "点击登录按钮" --target-text "登录成功"
    """
    # 检查 API Key
    if not config.llm.api_key:
        console.print(
            Panel(
                "请设置 OPENAI_API_KEY 环境变量或在 .env 文件中配置",
                title="错误",
                style="red",
            )
        )
        raise typer.Exit(1)

    # 显示配置
    console.print(Panel(
        f"[bold]起始 URL:[/bold] {start_url}\n"
        f"[bold]任务:[/bold] {task}\n"
        f"[bold]目标文本:[/bold] {target_text}\n"
        f"[bold]最大步数:[/bold] {max_steps}\n"
        f"[bold]无头模式:[/bold] {headless}\n"
        f"[bold]输出目录:[/bold] {output_dir}\n"
        f"[bold]LLM 模型:[/bold] {config.llm.model}",
        title="AutoSpider 配置",
        style="cyan",
    ))

    # 创建运行输入
    run_input = RunInput(
        start_url=start_url,
        task=task,
        target_text=target_text,
        max_steps=max_steps,
        headless=headless,
        output_dir=output_dir,
    )

    # 运行 Agent
    try:
        # 延迟导入避免循环依赖
        from .extractor.output import export_script_json, export_script_readable, print_script_summary
        
        script = run_async_safely(_run_agent(run_input))
        
        # 导出脚本
        output_path = Path(output_dir)
        export_script_json(script, output_path / "script.json")
        export_script_readable(script, output_path / "script.txt")
        
        # 打印摘要
        print_script_summary(script)
        
        if script.extracted_result:
            console.print(Panel(
                f"[green]成功提取目标内容！[/green]\n\n{script.extracted_result[:300]}",
                title="执行成功",
                style="green",
            ))
        else:
            console.print(Panel(
                "[yellow]任务执行完成，但未提取到目标内容[/yellow]",
                title="执行完成",
                style="yellow",
            ))
            
    except KeyboardInterrupt:
        console.print("\n[yellow]用户中断[/yellow]")
        raise typer.Exit(130)
    except Exception as e:
        console.print(Panel(
            f"[red]{str(e)}[/red]",
            title="执行错误",
            style="red",
        ))
        raise typer.Exit(1)


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
    console.print(Panel(
        f"[bold]列表页 URL:[/bold] {list_url}\n"
        f"[bold]任务描述:[/bold] {task}\n"
        f"[bold]探索数量:[/bold] {explore_count} 个详情页\n"
        f"[bold]无头模式:[/bold] {headless}\n"
        f"[bold]输出目录:[/bold] {output_dir}",
        title="配置生成器",
        style="cyan",
    ))

    # 运行配置生成器
    try:
        result = run_async_safely(_run_config_generator(
            list_url=list_url,
            task=task,
            explore_count=explore_count,
            headless=headless,
            output_dir=output_dir,
        ))
        
        # 显示结果
        console.print(Panel(
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
        ))
            
    except KeyboardInterrupt:
        console.print("\n[yellow]用户中断[/yellow]")
        raise typer.Exit(130)
    except Exception as e:
        console.print(Panel(
            f"[red]{str(e)}[/red]",
            title="执行错误",
            style="red",
        ))
        raise typer.Exit(1)


@app.command("batch-collect")
def batch_collect_command(
    config_path: str = typer.Option(
        ...,
        "--config-path",
        "-c",
        help="配置文件路径",
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
        console.print(Panel(
            f"[red]配置文件不存在: {config_path}[/red]\n\n"
            f"请先使用 'autospider generate-config' 生成配置文件",
            title="错误",
            style="red",
        ))
        raise typer.Exit(1)
    
    # 显示配置
    console.print(Panel(
        f"[bold]配置文件:[/bold] {config_path}\n"
        f"[bold]无头模式:[/bold] {headless}\n"
        f"[bold]输出目录:[/bold] {output_dir}",
        title="批量收集器",
        style="cyan",
    ))

    # 运行批量收集器
    try:
        result = asyncio.run(_run_batch_collector(
            config_path=config_path,
            headless=headless,
            output_dir=output_dir,
        ))
        
        # 显示结果
        console.print(Panel(
            f"[green]共收集到 {len(result.collected_urls)} 个详情页 URL[/green]\n\n"
            f"结果已保存到:\n"
            f"  - {output_dir}/collected_urls.json\n"
            f"  - {output_dir}/urls.txt",
            title="收集完成",
            style="green",
        ))
        
        # 显示前 10 个 URL
        if result.collected_urls:
            console.print("\n[bold]前 10 个 URL:[/bold]")
            for i, url in enumerate(result.collected_urls[:10], 1):
                console.print(f"  {i}. {url}")
            if len(result.collected_urls) > 10:
                console.print(f"  ... 还有 {len(result.collected_urls) - 10} 个")
            
    except KeyboardInterrupt:
        console.print("\n[yellow]用户中断[/yellow]")
        raise typer.Exit(130)
    except Exception as e:
        console.print(Panel(
            f"[red]{str(e)}[/red]",
            title="执行错误",
            style="red",
        ))
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
        console.print(Panel(
            f"[red]{str(e)}[/red]",
            title="输入验证错误",
            style="red",
        ))
        raise typer.Exit(1)
    
    # 显示配置
    console.print(Panel(
        f"[bold]列表页 URL:[/bold] {list_url}\n"
        f"[bold]任务描述:[/bold] {task}\n"
        f"[bold]探索数量:[/bold] {explore_count} 个详情页\n"
        f"[bold]无头模式:[/bold] {headless}\n"
        f"[bold]输出目录:[/bold] {output_dir}"
        + ("\n[bold yellow]模式:[/bold yellow] [yellow]预览模式 (dry-run)[/yellow]" if dry_run else ""),
        title="URL 收集器配置",
        style="cyan",
    ))
    
    # Dry-run 模式：只验证参数，不实际执行
    if dry_run:
        console.print(Panel(
            "[green]✓ 参数验证通过[/green]\n\n"
            "将执行以下操作：\n"
            f"  1. 打开浏览器访问 {list_url}\n"
            f"  2. 探索 {explore_count} 个详情页提取模式\n"
            f"  3. 收集详情页 URL 并保存到 {output_dir}/\n"
            f"  4. 生成爬虫脚本 {output_dir}/spider.py\n\n"
            "使用 [cyan]--no-dry-run[/cyan] 或移除 [cyan]--dry-run[/cyan] 执行实际操作",
            title="预览完成",
            style="green",
        ))
        return

    # 运行收集器（带进度条）
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task_id = progress.add_task("[cyan]初始化...", total=None)
            
            result = asyncio.run(_run_collector(
                list_url=list_url,
                task=task,
                explore_count=explore_count,
                headless=headless,
                output_dir=output_dir,
            ))
            
            progress.update(task_id, completed=True, description="[green]完成")
        
        # 显示结果
        console.print("\n")
        
        # 显示探索的详情页
        if result.detail_visits:
            table = Table(title="探索的详情页")
            table.add_column("序号", style="cyan")
            table.add_column("元素文本", style="green")
            table.add_column("详情页 URL", style="blue")
            
            for i, visit in enumerate(result.detail_visits, 1):
                table.add_row(
                    str(i),
                    visit.clicked_element_text[:30] + "..." if len(visit.clicked_element_text) > 30 else visit.clicked_element_text,
                    visit.detail_page_url[:60] + "..." if len(visit.detail_page_url) > 60 else visit.detail_page_url,
                )
            console.print(table)
        
        # 显示提取的模式
        if result.common_pattern:
            pattern = result.common_pattern
            console.print(Panel(
                f"[bold]标签模式:[/bold] {pattern.tag_pattern or '无'}\n"
                f"[bold]角色模式:[/bold] {pattern.role_pattern or '无'}\n"
                f"[bold]链接模式:[/bold] {pattern.href_pattern or '无'}\n"
                f"[bold]XPath 模式:[/bold] {pattern.xpath_pattern or '无'}\n"
                f"[bold]置信度:[/bold] {pattern.confidence:.1%}",
                title="提取的公共模式",
                style="magenta",
            ))
        
        # 显示收集结果
        console.print(Panel(
            f"[green]共收集到 {len(result.collected_urls)} 个详情页 URL[/green]\n\n"
            f"结果已保存到:\n"
            f"  - {output_dir}/collected_urls.json\n"
            f"  - {output_dir}/urls.txt",
            title="收集完成",
            style="green",
        ))
        
        # 显示前 10 个 URL
        if result.collected_urls:
            console.print("\n[bold]前 10 个 URL:[/bold]")
            for i, url in enumerate(result.collected_urls[:10], 1):
                console.print(f"  {i}. {url}")
            if len(result.collected_urls) > 10:
                console.print(f"  ... 还有 {len(result.collected_urls) - 10} 个")
            
    except KeyboardInterrupt:
        console.print("\n[yellow]用户中断[/yellow]")
        raise typer.Exit(130)
    except Exception as e:
        console.print(Panel(
            f"[red]{str(e)}[/red]",
            title="执行错误",
            style="red",
        ))
        raise typer.Exit(1)


async def _run_agent(run_input: RunInput):
    """异步运行 Agent"""
    async with create_browser_session(
        headless=run_input.headless,
        close_engine=True,
    ) as session:
        return await run_agent(session.page, run_input)


async def _run_config_generator(
    list_url: str,
    task: str,
    explore_count: int,
    headless: bool,
    output_dir: str,
):
    """异步运行配置生成器"""
    from .extractor.config_generator import generate_collection_config
    
    async with create_browser_session(headless=headless, close_engine=True) as session:
        return await generate_collection_config(
            page=session.page,
            list_url=list_url,
            task_description=task,
            explore_count=explore_count,
            output_dir=output_dir,
        )


async def _run_batch_collector(
    config_path: str,
    headless: bool,
    output_dir: str,
):
    """异步运行批量收集器"""
    from .crawler.batch_collector import batch_collect_urls
    
    async with create_browser_session(headless=headless, close_engine=True) as session:
        return await batch_collect_urls(
            page=session.page,
            config_path=config_path,
            output_dir=output_dir,
        )


async def _run_collector(
    list_url: str,
    task: str,
    explore_count: int,
    headless: bool,
    output_dir: str,
):
    """异步运行 URL 收集器（完整流程）"""
    from .crawler.url_collector import collect_detail_urls
    
    async with create_browser_session(headless=headless, close_engine=True) as session:
        return await collect_detail_urls(
            page=session.page,
            list_url=list_url,
            task_description=task,
            explore_count=explore_count,
            output_dir=output_dir,
        )


async def _run_field_extractor(
    urls: list[str] | None,
    fields_config: list[dict],
    explore_count: int,
    validate_count: int,
    headless: bool,
    output_dir: str,
):
    """异步运行字段提取器"""
    from .field import (
        FieldDefinition,
        BatchFieldExtractor,
    )
    
    # 转换字段配置
    fields = [
        FieldDefinition(
            name=f["name"],
            description=f.get("description", f["name"]),
            required=f.get("required", True),
            data_type=f.get("data_type", "text"),
            example=f.get("example"),
        )
        for f in fields_config
    ]
    
    redis_manager = None
    if urls is None:
        if not config.redis.enabled:
            raise ValueError("Redis 未启用，请设置 REDIS_ENABLED=true")
        try:
            from .common.storage.redis_manager import RedisManager
        except ImportError as e:
            raise ImportError("Redis 依赖未安装，请使用 pip install autospider[redis] 安装") from e
        
        redis_manager = RedisManager(
            host=config.redis.host,
            port=config.redis.port,
            password=config.redis.password,
            db=config.redis.db,
            key_prefix=config.redis.key_prefix,
            logger=logger,
        )
    
    async with create_browser_session(headless=headless, close_engine=True) as session:
        extractor = BatchFieldExtractor(
            page=session.page,
            fields=fields,
            redis_manager=redis_manager,
            explore_count=explore_count,
            validate_count=validate_count,
            output_dir=output_dir,
        )
        return await extractor.run(urls=urls)


async def _run_batch_xpath_extractor(
    urls: list[str] | None,
    fields_config: list[dict],
    headless: bool,
    output_dir: str,
):
    """异步运行批量 XPath 字段提取器"""
    from .field import BatchXPathExtractor

    if urls is None:
        if not config.redis.enabled:
            raise ValueError("Redis 未启用，请设置 REDIS_ENABLED=true")
        try:
            from .common.storage.redis_manager import RedisManager
        except ImportError as e:
            raise ImportError("Redis 依赖未安装，请使用 pip install autospider[redis] 安装") from e

        redis_manager = RedisManager(
            host=config.redis.host,
            port=config.redis.port,
            password=config.redis.password,
            db=config.redis.db,
            key_prefix=config.redis.key_prefix,
            logger=logger,
        )
        try:
            await redis_manager.connect()
            items = await redis_manager.get_active_items()
            urls = list(items)
        except Exception as e:
            raise ValueError(f"Redis 读取失败: {e}") from e

    if not urls:
        raise ValueError("未获取到 URL，请提供 --urls 或检查 Redis")

    async with create_browser_session(headless=headless, close_engine=True) as session:
        extractor = BatchXPathExtractor(
            page=session.page,
            fields_config=fields_config,
            output_dir=output_dir,
        )
        return await extractor.run(urls=urls)


@app.command("extract-fields")
def extract_fields_command(
    urls: Optional[str] = typer.Option(
        None,
        "--urls",
        "-u",
        help="详情页 URL，多个用逗号分隔，或传入包含 URL 列表的 JSON 文件路径（不传则从 Redis 读取）",
    ),
    fields: str = typer.Option(
        ...,
        "--fields",
        "-f",
        help="字段配置 JSON 文件路径或 JSON 字符串",
    ),
    explore_count: int = typer.Option(
        3,
        "--explore-count",
        "-n",
        help="探索阶段的 URL 数量",
    ),
    validate_count: int = typer.Option(
        2,
        "--validate-count",
        "-v",
        help="校验阶段的 URL 数量",
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
    从详情页提取目标字段
    
    流程:
    1. 从提供的 URL 列表中选取若干进行探索（未提供时从 Redis 读取）
    2. 使用 SoM + LLM 导航到目标字段区域
    3. 提取字段值并生成 XPath
    4. 分析多个页面的 XPath，提取公共模式
    5. 使用额外 URL 校验公共 XPath
    6. 输出提取配置供批量使用
    
    示例:
        # 使用 URL 列表和字段配置文件
        autospider extract-fields --urls "urls.json" --fields "fields.json"
        
        # 使用逗号分隔的 URL 和 JSON 字符串配置
        autospider extract-fields --urls "http://a.com,http://b.com" --fields '[{"name":"title","description":"标题"}]'
    """
    import json
    
    # 解析 URL 列表
    url_list = None
    use_redis = urls is None or not urls.strip()
    if use_redis:
        if not config.redis.enabled:
            console.print(Panel(
                "[red]未启用 Redis，无法从 Redis 读取 URL。请设置 REDIS_ENABLED=true[/red]",
                title="错误",
                style="red",
            ))
            raise typer.Exit(1)
    else:
        if urls.endswith(".json"):
            # JSON 文件
            urls_file = Path(urls)
            if not urls_file.exists():
                console.print(Panel(f"[red]URL 文件不存在: {urls}[/red]", title="错误", style="red"))
                raise typer.Exit(1)
            with open(urls_file, encoding="utf-8") as f:
                url_list = json.load(f)
        else:
            # 逗号分隔的 URL
            url_list = [u.strip() for u in urls.split(",") if u.strip()]
        
        if not url_list:
            console.print(Panel("[red]未提供有效的 URL[/red]", title="错误", style="red"))
            raise typer.Exit(1)
    
    # 解析字段配置
    fields_config = []
    if fields.endswith(".json") or fields.endswith(".yaml"):
        # 配置文件
        fields_file = Path(fields)
        if not fields_file.exists():
            console.print(Panel(f"[red]字段配置文件不存在: {fields}[/red]", title="错误", style="red"))
            raise typer.Exit(1)
        with open(fields_file, encoding="utf-8") as f:
            if fields.endswith(".yaml"):
                import yaml
                fields_config = yaml.safe_load(f)
            else:
                fields_config = json.load(f)
    else:
        # JSON 字符串
        try:
            fields_config = json.loads(fields)
        except json.JSONDecodeError as e:
            console.print(Panel(f"[red]字段配置 JSON 解析失败: {e}[/red]", title="错误", style="red"))
            raise typer.Exit(1)
    
    if not fields_config:
        console.print(Panel("[red]未提供有效的字段配置[/red]", title="错误", style="red"))
        raise typer.Exit(1)
    
    # 显示配置
    url_summary = (
        f"Redis (key_prefix={config.redis.key_prefix})"
        if use_redis
        else f"{len(url_list)} 个"
    )
    console.print(Panel(
        f"[bold]URL 来源:[/bold] {url_summary}\n"
        f"[bold]字段数量:[/bold] {len(fields_config)} 个\n"
        f"[bold]字段列表:[/bold] {', '.join(f['name'] for f in fields_config)}\n"
        f"[bold]探索数量:[/bold] {explore_count}\n"
        f"[bold]校验数量:[/bold] {validate_count}\n"
        f"[bold]无头模式:[/bold] {headless}\n"
        f"[bold]输出目录:[/bold] {output_dir}",
        title="字段提取器配置",
        style="cyan",
    ))
    
    # 运行提取器
    try:
        result = asyncio.run(_run_field_extractor(
            urls=url_list,
            fields_config=fields_config,
            explore_count=explore_count,
            validate_count=validate_count,
            headless=headless,
            output_dir=output_dir,
        ))
        
        # 显示结果
        success_count = sum(1 for r in result.exploration_records if r.success)
        
        console.print(Panel(
            f"[green]字段提取完成！[/green]\n\n"
            f"探索结果:\n"
            f"  - 成功提取: {success_count}/{len(result.exploration_records)} 个页面\n"
            f"  - 公共 XPath: {len(result.common_xpaths)} 个字段\n"
            f"  - 校验通过: {'是' if result.validation_success else '否'}\n\n"
            f"输出文件:\n"
            f"  - {output_dir}/extraction_config.json\n"
            f"  - {output_dir}/extraction_result.json",
            title="提取完成",
            style="green",
        ))
        
        # 显示公共 XPath
        if result.common_xpaths:
            console.print("\n[bold]公共 XPath 模式:[/bold]")
            for xpath_info in result.common_xpaths:
                status = "✓" if xpath_info.validated else "?"
                console.print(f"  {status} {xpath_info.field_name}: {xpath_info.xpath_pattern}")
                console.print(f"      置信度: {xpath_info.confidence:.0%}")
            
    except KeyboardInterrupt:
        console.print("\n[yellow]用户中断[/yellow]")
        raise typer.Exit(130)
    except Exception as e:
        console.print(Panel(
            f"[red]{str(e)}[/red]",
            title="执行错误",
            style="red",
        ))
        import traceback
        traceback.print_exc()
        raise typer.Exit(1)


@app.command("batch-extract")
def batch_extract_command(
    config_path: str = typer.Option(
        ...,
        "--config-path",
        "-c",
        help="extract-fields 输出的 extraction_config.json 路径",
    ),
    urls: Optional[str] = typer.Option(
        None,
        "--urls",
        "-u",
        help="详情页 URL，多个用逗号分隔，或传入包含 URL 列表的 JSON 文件路径（不传则从 Redis 读取）",
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
    基于 extraction_config.json 批量提取字段

    示例:
        autospider batch-extract --config-path output/extraction_config.json --urls "output/collected_urls.json"
    """
    import json

    config_file = Path(config_path)
    if not config_file.exists():
        console.print(Panel(f"[red]配置文件不存在: {config_path}[/red]", title="错误", style="red"))
        raise typer.Exit(1)

    try:
        config_data = json.loads(config_file.read_text(encoding="utf-8"))
    except Exception as e:
        console.print(Panel(f"[red]配置文件解析失败: {e}[/red]", title="错误", style="red"))
        raise typer.Exit(1)

    fields_config = config_data.get("fields") if isinstance(config_data, dict) else None
    if not isinstance(fields_config, list) or not fields_config:
        console.print(Panel("[red]配置文件中缺少有效的 fields[/red]", title="错误", style="red"))
        raise typer.Exit(1)

    url_list = None
    use_redis = urls is None or not urls.strip()
    if use_redis:
        if not config.redis.enabled:
            console.print(Panel(
                "[red]未启用 Redis，无法从 Redis 读取 URL。请设置 REDIS_ENABLED=true[/red]",
                title="错误",
                style="red",
            ))
            raise typer.Exit(1)
    else:
        if urls.endswith(".json"):
            urls_file = Path(urls)
            if not urls_file.exists():
                console.print(Panel(f"[red]URL 文件不存在: {urls}[/red]", title="错误", style="red"))
                raise typer.Exit(1)
            with open(urls_file, encoding="utf-8") as f:
                url_data = json.load(f)
            if isinstance(url_data, dict):
                url_list = url_data.get("collected_urls") or url_data.get("urls")
            elif isinstance(url_data, list):
                url_list = url_data
        else:
            url_list = [u.strip() for u in urls.split(",") if u.strip()]

        if not url_list:
            console.print(Panel("[red]未提供有效的 URL[/red]", title="错误", style="red"))
            raise typer.Exit(1)

    url_summary = (
        f"Redis (key_prefix={config.redis.key_prefix})"
        if use_redis
        else f"{len(url_list)} 个"
    )
    field_names = [f.get("name", "") for f in fields_config]
    console.print(Panel(
        f"[bold]URL 来源:[/bold] {url_summary}\n"
        f"[bold]字段数量:[/bold] {len(fields_config)} 个\n"
        f"[bold]字段列表:[/bold] {', '.join(field_names)}\n"
        f"[bold]无头模式:[/bold] {headless}\n"
        f"[bold]输出目录:[/bold] {output_dir}",
        title="批量字段提取器配置",
        style="cyan",
    ))

    missing_xpath_fields = [f.get("name") for f in fields_config if not f.get("xpath")]
    if missing_xpath_fields:
        console.print(Panel(
            f"[yellow]以下字段缺少 XPath，批量提取时可能失败:[/yellow]\n"
            f"{', '.join(missing_xpath_fields)}",
            title="提示",
            style="yellow",
        ))

    try:
        result = asyncio.run(_run_batch_xpath_extractor(
            urls=url_list,
            fields_config=fields_config,
            headless=headless,
            output_dir=output_dir,
        ))

        console.print(Panel(
            f"[green]批量字段提取完成！[/green]\n\n"
            f"总 URL: {result.get('total_urls', 0)}\n"
            f"成功页面: {result.get('success_count', 0)}/{result.get('total_urls', 0)}\n\n"
            f"输出文件:\n"
            f"  - {output_dir}/batch_extraction_result.json\n"
            f"  - {output_dir}/extracted_items.json",
            title="提取完成",
            style="green",
        ))

    except KeyboardInterrupt:
        console.print("\n[yellow]用户中断[/yellow]")
        raise typer.Exit(130)
    except Exception as e:
        console.print(Panel(
            f"[red]{str(e)}[/red]",
            title="执行错误",
            style="red",
        ))
        raise typer.Exit(1)

def main():
    """CLI 入口点
    
    供 pyproject.toml 中 [project.scripts] 调用。
    """
    app()


if __name__ == "__main__":
    main()
