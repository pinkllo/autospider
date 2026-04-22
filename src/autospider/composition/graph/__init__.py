from __future__ import annotations

from importlib import import_module

_EXPORTS = {
    "DispatchDecision": "control_types",
    "GraphError": "types",
    "GraphInput": "types",
    "GraphResult": "types",
    "GraphRunner": "runner",
    "GraphState": "state",
    "PlanSpec": "control_types",
    "RecoveryDirective": "control_types",
    "build_chat_execution_params": "execution_handoff",
    "build_chat_review_payload": "execution_handoff",
    "build_decision_context": "decision_context",
    "build_default_dispatch_policy": "control_types",
    "build_default_recovery_policy": "control_types",
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
