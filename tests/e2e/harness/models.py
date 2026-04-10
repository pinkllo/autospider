from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class GraphOutputFiles:
    merged_results_path: Path
    merged_summary_path: Path


@dataclass(frozen=True, slots=True)
class GraphHarnessResult:
    graph_result: dict[str, Any]
    output_files: GraphOutputFiles | None = None
    raw_records: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    raw_summary: dict[str, Any] = field(default_factory=dict)
    normalized_records: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    normalized_summary: dict[str, Any] = field(default_factory=dict)
