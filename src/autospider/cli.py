"""CLI 入口"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

from .browser import create_browser_session
from .config import config
from .graph import run_agent
from .output import export_script_json, export_script_readable, print_script_summary
from .types import RunInput

app = typer.Typer(
    name="autospider",
    help="纯视觉 SoM 浏览器 Agent - 使用 LangGraph + 多模态 LLM",
)
console = Console()


@app.command()
def main(
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
        autospider --start-url "https://example.com" --task "点击登录按钮" --target-text "登录成功"
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


async def _run_agent(run_input: RunInput):
    """异步运行 Agent"""
    async with create_browser_session(
        headless=run_input.headless,
    ) as session:
        return await run_agent(session.page, run_input)


if __name__ == "__main__":
    app()
