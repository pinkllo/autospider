from __future__ import annotations

from collections.abc import Iterable, Mapping
import json
from pathlib import Path
from typing import Any

from .errors import MissingOutputArtifactError, OutputArtifactError
from .models import GraphOutputFiles


def resolve_output_files(
    *,
    graph_result: Mapping[str, Any],
    output_dir: Path,
) -> GraphOutputFiles:
    merged_results_path = _resolve_artifact_path(
        artifacts=graph_result.get("artifacts"),
        label="merged_results",
        default_path=output_dir / "merged_results.jsonl",
    )
    merged_summary_path = _resolve_artifact_path(
        artifacts=graph_result.get("artifacts"),
        label="merged_summary",
        default_path=output_dir / "merged_summary.json",
    )
    _require_file(label="merged_results", path=merged_results_path)
    _require_file(label="merged_summary", path=merged_summary_path)
    return GraphOutputFiles(
        merged_results_path=merged_results_path,
        merged_summary_path=merged_summary_path,
    )


def load_jsonl_records(path: Path) -> tuple[dict[str, Any], ...]:
    records: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise OutputArtifactError(f"jsonl record must be an object: {path}")
        records.append({str(key): value for key, value in payload.items()})
    return tuple(records)


def load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise OutputArtifactError(f"json object expected: {path}")
    return {str(key): value for key, value in payload.items()}


def _resolve_artifact_path(
    *,
    artifacts: Any,
    label: str,
    default_path: Path,
) -> Path:
    artifact_path = _find_artifact_path(artifacts=artifacts, label=label)
    if artifact_path is not None:
        return artifact_path
    return default_path


def _find_artifact_path(*, artifacts: Any, label: str) -> Path | None:
    for item in _iter_artifacts(artifacts):
        item_label = str(item.get("label") or "").strip()
        item_path = str(item.get("path") or "").strip()
        if item_label != label or not item_path:
            continue
        return Path(item_path)
    return None


def _iter_artifacts(artifacts: Any) -> Iterable[Mapping[str, Any]]:
    if not isinstance(artifacts, list):
        return ()
    return tuple(item for item in artifacts if isinstance(item, Mapping))


def _require_file(*, label: str, path: Path) -> None:
    if not path.is_file():
        raise MissingOutputArtifactError(label=label, path=path)
