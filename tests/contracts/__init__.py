from __future__ import annotations

import re
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .pipeline_runtime import (
    ContractRunArtifacts as ContractRunArtifacts,
    run_contract_pipeline as run_contract_pipeline,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMP_ROOT = REPO_ROOT / ".tmp" / "contracts"


def normalize_help_surface(text: str) -> dict[str, Any]:
    lines = [line.rstrip() for line in text.splitlines()]
    usage = next((line.strip() for line in lines if line.strip().startswith("Usage:")), "")
    description = _first_content_line(lines, usage)
    return {
        "usage": usage,
        "description": description,
        "options": _extract_options(text),
        "commands": _extract_commands(lines),
    }


def snapshot_shape(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: snapshot_shape(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [snapshot_shape(item) for item in value]
    return type(value).__name__


def directory_files(root: Path) -> list[str]:
    return sorted(
        str(path.relative_to(root)).replace("\\", "/") for path in root.rglob("*") if path.is_file()
    )


@contextmanager
def contract_tmp_dir() -> Iterator[Path]:
    TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    path = TEMP_ROOT / "workspace"
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _first_content_line(lines: list[str], usage: str) -> str:
    for line in lines:
        text = line.strip()
        if not text or text == usage or text == "Options:" or text == "Commands:":
            continue
        return text
    return ""


def _extract_commands(lines: list[str]) -> list[str]:
    commands: list[str] = []
    in_commands = False
    for line in lines:
        stripped = line.strip()
        if stripped == "Commands:":
            in_commands = True
            continue
        if in_commands and not stripped:
            break
        if in_commands and line.startswith("  "):
            commands.append(stripped.split()[0])
    return commands


def _extract_options(text: str) -> list[str]:
    options = re.findall(r"--[a-z0-9-]+|(?<!-)-[a-z]\b", text, flags=re.IGNORECASE)
    unique: list[str] = []
    for option in options:
        if option not in unique:
            unique.append(option)
    return unique
