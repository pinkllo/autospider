"""CLI 入口"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .common.browser import create_browser_session
from .common.config import config
from .extractor.graph import run_agent
from .common.types import RunInput

app = typer.Typer(
    name="autospider",
    help="纯视觉 SoM 浏览器 Agent - 使用 LangGraph + 多模态 LLM",
)
console = Console()


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
        
        script = asyncio.run(_run_agent(run_input))
        
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
        result = asyncio.run(_run_config_generator(
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
    # 显示配置
    console.print(Panel(
        f"[bold]列表页 URL:[/bold] {list_url}\n"
        f"[bold]任务描述:[/bold] {task}\n"
        f"[bold]探索数量:[/bold] {explore_count} 个详情页\n"
        f"[bold]无头模式:[/bold] {headless}\n"
        f"[bold]输出目录:[/bold] {output_dir}",
        title="URL 收集器配置",
        style="cyan",
    ))

    # 运行收集器
    try:
        result = asyncio.run(_run_collector(
            list_url=list_url,
            task=task,
            explore_count=explore_count,
            headless=headless,
            output_dir=output_dir,
        ))
        
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
    
    async with create_browser_session(headless=headless) as session:
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
    
    async with create_browser_session(headless=headless) as session:
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
    
    async with create_browser_session(headless=headless) as session:
        return await collect_detail_urls(
            page=session.page,
            list_url=list_url,
            task_description=task,
            explore_count=explore_count,
            output_dir=output_dir,
        )


if __name__ == "__main__":
    app()

