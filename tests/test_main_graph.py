from __future__ import annotations

import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autospider.graph.main_graph import resolve_node_outcome


def test_resolve_node_outcome_uses_requested_stage_status() -> None:
    state = {
        "planning": {"status": "ok"},
        "dispatch": {"status": "fatal"},
        "node_status": "ok",
    }

    assert resolve_node_outcome(state, stage="dispatch") == "error"
