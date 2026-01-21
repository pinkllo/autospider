"""
handlers 子模块

导入此模块将触发所有内置处理器的自动注册。
"""

# 导入所有内置处理器，触发其自动注册
from . import login_handler  # noqa: F401

# 未来扩展：
# from . import captcha_handler
# from . import rate_limit_handler

# 导出基类供外部继承
from .base import BaseAnomalyHandler

__all__ = ["BaseAnomalyHandler"]
