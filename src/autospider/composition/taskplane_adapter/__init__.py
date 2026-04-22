"""Autospider-specific adapters for TaskPlane."""

from .graph_integration import (
    close_all_taskplane_sessions,
    close_taskplane_session,
    ensure_taskplane_plan_registered,
    ensure_taskplane_runtime,
    get_taskplane_scheduler,
    register_taskplane_plan,
)
from .plan_bridge import PlanBridge
from .result_bridge import ResultBridge
from .subtask_bridge import SubtaskBridge

__all__ = [
    "PlanBridge",
    "ResultBridge",
    "SubtaskBridge",
    "close_all_taskplane_sessions",
    "close_taskplane_session",
    "ensure_taskplane_plan_registered",
    "ensure_taskplane_runtime",
    "get_taskplane_scheduler",
    "register_taskplane_plan",
]
