"""浏览器模块。

BrowserRuntimeSession 是主路径生命周期抽象。
"""

from .actions import ActionExecutor
from .composition import build_default_handlers
from .engine import BrowserEngine, get_browser_engine, shutdown_browser_engine
from .guard import PageGuard
from .guarded_page import GuardedPage
from .handlers.base import BaseAnomalyHandler
from .registry import (
    HandlerRegistry,
    disable_handler,
    enable_handler,
    get_handlers,
    get_registry,
    register_handler,
)
from .runtime import BrowserRuntimeSession

__all__ = [
    "BrowserEngine",
    "BrowserRuntimeSession",
    "get_browser_engine",
    "PageGuard",
    "GuardedPage",
    "build_default_handlers",
    "shutdown_browser_engine",
    "ActionExecutor",
    "BaseAnomalyHandler",
    "HandlerRegistry",
    "register_handler",
    "get_handlers",
    "enable_handler",
    "disable_handler",
    "get_registry",
]
