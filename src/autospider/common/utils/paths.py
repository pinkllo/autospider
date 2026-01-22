"""Path helpers for locating repository resources."""

from __future__ import annotations

from pathlib import Path


def _find_repo_root(start: Path) -> Path:
    base = start if start.is_dir() else start.parent
    for parent in [base] + list(base.parents):
        if (parent / "pyproject.toml").exists() and (parent / "prompts").is_dir():
            return parent
    for parent in [base] + list(base.parents):
        if (parent / "prompts").is_dir():
            return parent
    return base


def get_repo_root() -> Path:
    """Return the repository root used for prompt resolution."""
    return _find_repo_root(Path(__file__).resolve())


def get_prompt_path(name: str) -> str:
    """Return the absolute path to a prompt file by name."""
    return str((get_repo_root() / "prompts" / name).resolve())
