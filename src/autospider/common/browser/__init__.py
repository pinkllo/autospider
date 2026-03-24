"""浏览器模块"""

from .actions import ActionExecutor
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
from .session import BrowserSession, create_browser_session

__all__ = [
    "BrowserEngine",
    "get_browser_engine",
    "PageGuard",
    "GuardedPage",
    "BrowserSession",
    "create_browser_session",
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
