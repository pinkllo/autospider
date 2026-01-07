"""Common模块 - 公共工具和基础设施

该模块提供：
- 全局配置管理
- 浏览器操作工具
- SoM可视化标记
- 存储和持久化
- 类型定义
- 日志系统
- 异常类
- 常量定义
- 输入验证
"""

from .config import config, Config
from .logger import get_logger, console
from .exceptions import (
    AutoSpiderError,
    LLMError,
    LLMResponseError,
    BrowserError,
    PageLoadError,
    ValidationError,
    StorageError,
    RedisConnectionError,
)
from .constants import (
    DEFAULT_SCROLL_PIXELS,
    DEFAULT_RETRY_COUNT,
    DEFAULT_PAGE_TIMEOUT_MS,
)

__all__ = [
    # 配置
    "config",
    "Config",
    # 日志
    "get_logger",
    "console",
    # 异常
    "AutoSpiderError",
    "LLMError",
    "LLMResponseError",
    "BrowserError",
    "PageLoadError",
    "ValidationError",
    "StorageError",
    "RedisConnectionError",
    # 常量
    "DEFAULT_SCROLL_PIXELS",
    "DEFAULT_RETRY_COUNT",
    "DEFAULT_PAGE_TIMEOUT_MS",
]
