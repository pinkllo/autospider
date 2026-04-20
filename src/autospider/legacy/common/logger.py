"""统一日志系统

提供项目统一的日志配置，支持 Rich 格式化输出。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from dotenv import load_dotenv
from rich.console import Console
from rich.logging import RichHandler

from .utils.paths import get_repo_root, resolve_output_path, resolve_repo_path

if TYPE_CHECKING:
    pass


# 全局控制台实例
console = Console()
_BOOTSTRAPPED = False
_CURRENT_LOG_FILE = ""
_CONSOLE_HANDLER: logging.Handler | None = None
_FILE_HANDLER: logging.Handler | None = None

# 日志级别映射
LOG_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def _load_logging_environment() -> None:
    env_file = get_repo_root() / ".env"
    load_dotenv(env_file, override=False)


def get_log_level() -> int:
    """从环境变量获取日志级别

    Returns:
        日志级别常量
    """
    _load_logging_environment()
    level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    return LOG_LEVEL_MAP.get(level_str, logging.INFO)


def _should_show_locals() -> bool:
    _load_logging_environment()
    return os.getenv("LOG_SHOW_LOCALS", "false").lower() == "true"


def _resolve_runtime_log_file(output_dir: str | None = None) -> Path:
    if output_dir:
        return resolve_output_path(output_dir, "runtime.log")

    _load_logging_environment()
    configured = os.getenv("LOG_FILE", "output/runtime.log").strip() or "output/runtime.log"
    return resolve_repo_path(configured)


def _build_console_handler(level: int) -> logging.Handler:
    handler = RichHandler(
        console=console,
        show_time=True,
        show_path=False,
        rich_tracebacks=True,
        tracebacks_show_locals=_should_show_locals(),
        markup=False,
    )
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter("%(message)s", datefmt="[%X]"))
    return handler


def _build_file_handler(log_file: Path, level: int) -> logging.Handler:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    return handler


def _configure_root_logger(level: int, log_file: Path) -> None:
    global _CONSOLE_HANDLER, _FILE_HANDLER, _CURRENT_LOG_FILE
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    if _CONSOLE_HANDLER is None:
        _CONSOLE_HANDLER = _build_console_handler(level)
        root_logger.addHandler(_CONSOLE_HANDLER)
    else:
        _CONSOLE_HANDLER.setLevel(level)
        root_logger.addHandler(_CONSOLE_HANDLER)

    target_log_file = str(log_file)
    if _FILE_HANDLER is not None and _CURRENT_LOG_FILE != target_log_file:
        root_logger.removeHandler(_FILE_HANDLER)
        _FILE_HANDLER.close()
        _FILE_HANDLER = None

    if _FILE_HANDLER is None:
        _FILE_HANDLER = _build_file_handler(log_file, level)
        _CURRENT_LOG_FILE = target_log_file
        root_logger.addHandler(_FILE_HANDLER)
    else:
        _FILE_HANDLER.setLevel(level)
        root_logger.addHandler(_FILE_HANDLER)


def bootstrap_logging(*, output_dir: str | None = None) -> None:
    """初始化统一日志系统，并按需切换输出目录。"""
    global _BOOTSTRAPPED
    level = get_log_level()
    log_file = _resolve_runtime_log_file(output_dir)
    _configure_root_logger(level, log_file)
    _BOOTSTRAPPED = True


def get_logger(name: str) -> logging.Logger:
    """获取统一配置的日志器

    所有模块应使用此函数获取日志器，以确保统一的格式和输出。

    Args:
        name: 日志器名称，通常使用 __name__

    Returns:
        配置好的日志器实例

    Example:
        >>> from autospider.legacy.common.logger import get_logger
        >>> logger = get_logger(__name__)
        >>> logger.info("这是一条日志")
    """
    if not _BOOTSTRAPPED:
        bootstrap_logging()
    logger = logging.getLogger(name)
    logger.setLevel(logging.NOTSET)
    logger.propagate = True
    return logger


def setup_file_logging(
    logger: logging.Logger,
    log_file: str,
    level: int = logging.DEBUG,
) -> None:
    """为日志器添加文件输出

    Args:
        logger: 日志器实例
        log_file: 日志文件路径
        level: 文件日志级别
    """
    resolved = resolve_repo_path(log_file)
    file_handler = _build_file_handler(resolved, level)
    logger.addHandler(file_handler)


class LogContext:
    """日志上下文管理器

    用于在日志中添加上下文信息。

    Example:
        >>> with LogContext(logger, page_num=5, url="https://example.com"):
        ...     logger.info("处理页面")
    """

    def __init__(self, logger: logging.Logger, **context):
        self.logger = logger
        self.context = context
        self._old_extra = {}

    def __enter__(self):
        # 保存旧的 extra 并设置新的
        for key, value in self.context.items():
            self._old_extra[key] = getattr(self.logger, key, None)
            setattr(self.logger, key, value)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # 恢复旧的 extra
        for key, old_value in self._old_extra.items():
            if old_value is None:
                delattr(self.logger, key)
            else:
                setattr(self.logger, key, old_value)
        return False


# 预配置的模块日志器
def get_crawler_logger() -> logging.Logger:
    """获取爬虫模块日志器"""
    return get_logger("autospider.crawler")


def get_llm_logger() -> logging.Logger:
    """获取 LLM 模块日志器"""
    return get_logger("autospider.llm")


def get_browser_logger() -> logging.Logger:
    """获取浏览器模块日志器"""
    return get_logger("autospider.browser")
