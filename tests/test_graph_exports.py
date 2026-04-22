from __future__ import annotations

import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import autospider.composition.graph as graph_exports
from autospider.composition.graph.control_types import (
    PlanSpec,
    build_default_dispatch_policy,
)
from autospider.composition.graph.execution_handoff import build_chat_execution_params


def test_graph_package_reexports_point_to_concrete_modules() -> None:
    assert graph_exports.PlanSpec is PlanSpec
    assert graph_exports.build_default_dispatch_policy is build_default_dispatch_policy
    assert graph_exports.build_chat_execution_params is build_chat_execution_params
