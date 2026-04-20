"""LangGraph 主链路编排层。"""

from .types import EntryMode, GraphError, GraphInput, GraphResult

__all__ = [
    "EntryMode",
    "GraphError",
    "GraphInput",
    "GraphResult",
    "GraphRunner",
]


def __getattr__(name: str):
    if name != "GraphRunner":
        raise AttributeError(name)
    from .runner import GraphRunner

    return GraphRunner
