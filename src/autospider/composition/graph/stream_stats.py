"""Helpers for collecting graph execution stream stats."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class GraphStreamStats:
    total_graph_steps: int = 0
    graph_steps_by_node: dict[str, int] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "total_graph_steps": self.total_graph_steps,
            "graph_steps_by_node": dict(self.graph_steps_by_node),
        }


async def collect_stream_execution(
    graph: Any,
    graph_input: dict[str, Any] | Any,
    *,
    config: dict[str, Any],
) -> tuple[dict[str, Any], GraphStreamStats]:
    final_state: dict[str, Any] = {}
    total_steps = 0
    per_node: dict[str, int] = {}
    async for mode, payload in graph.astream(
        graph_input,
        config=config,
        stream_mode=["updates", "values"],
    ):
        if mode == "values":
            final_state = dict(payload or {})
            continue
        if mode != "updates":
            continue
        for node_name in _update_node_names(payload):
            total_steps += 1
            per_node[node_name] = per_node.get(node_name, 0) + 1
    return final_state, GraphStreamStats(total_graph_steps=total_steps, graph_steps_by_node=per_node)


def _update_node_names(payload: Any) -> list[str]:
    if isinstance(payload, dict):
        return [str(key) for key in payload.keys()]
    return []

