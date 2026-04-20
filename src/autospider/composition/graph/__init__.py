from __future__ import annotations

from importlib import import_module

_EXPORTS = {
    "DispatchDecision": "controls",
    "GraphError": "types",
    "GraphInput": "types",
    "GraphResult": "types",
    "GraphRunner": "runner",
    "GraphState": "state",
    "PlanSpec": "controls",
    "RecoveryDirective": "controls",
    "build_chat_execution_params": "handoff",
    "build_chat_review_payload": "handoff",
    "build_decision_context": "decision_context",
    "build_default_dispatch_policy": "controls",
    "build_default_recovery_policy": "controls",
    "build_main_graph": "main_graph",
    "graph_checkpoint_enabled": "checkpoint",
    "graph_checkpointer_session": "checkpoint",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    module = import_module(f"{__name__}.{module_name}")
    return getattr(module, name)
