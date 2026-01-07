"""断点恢复模块

用于管理 checkpoint 相关功能
"""

from .rate_controller import AdaptiveRateController
from .resume_strategy import (
    ResumeCoordinator,
    ResumeStrategy,
    SmartSkipStrategy,
    URLPatternStrategy,
    WidgetJumpStrategy,
)

__all__ = [
    "AdaptiveRateController",
    "ResumeCoordinator",
    "ResumeStrategy",
    "SmartSkipStrategy",
    "URLPatternStrategy",
    "WidgetJumpStrategy",
]
