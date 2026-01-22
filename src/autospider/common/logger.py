"""统一日志系统

提供项目统一的日志配置，支持 Rich 格式化输出。
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from rich.console import Console
from rich.logging import RichHandler

if TYPE_CHECKING:
    pass


# 全局控制台实例
console = Console()

# 日志级别映射
LOG_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def get_log_level() -> int:
    """从环境变量获取日志级别

    Returns:
        日志级别常量
    """
    level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    return LOG_LEVEL_MAP.get(level_str, logging.INFO)


def get_logger(name: str) -> logging.Logger:
    """获取统一配置的日志器

    所有模块应使用此函数获取日志器，以确保统一的格式和输出。

    Args:
        name: 日志器名称，通常使用 __name__

    Returns:
        配置好的日志器实例

    Example:
        >>> from autospider.common.logger import get_logger
        >>> logger = get_logger(__name__)
        >>> logger.info("这是一条日志")
    """
    logger = logging.getLogger(name)

    # 避免重复配置
    if logger.handlers:
        return logger

    # 设置日志级别
    log_level = get_log_level()
    logger.setLevel(log_level)

    # 配置 Rich 处理器
    rich_handler = RichHandler(
        console=console,
        show_time=True,
        show_path=False,
        rich_tracebacks=True,
        tracebacks_show_locals=os.getenv("LOG_SHOW_LOCALS", "false").lower() == "true",
        markup=True,
    )
    rich_handler.setLevel(log_level)

    # 设置格式
    formatter = logging.Formatter(
        "%(message)s",
        datefmt="[%X]",
    )
    rich_handler.setFormatter(formatter)

    logger.addHandler(rich_handler)

    # 阻止日志传播到父级
    logger.propagate = False

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
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(level)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(formatter)

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
