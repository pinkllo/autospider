"""Path helpers for locating repository resources."""

from __future__ import annotations

from pathlib import Path


def _find_project_root(start: Path) -> Path:
    base = start if start.is_dir() else start.parent
    for parent in [base] + list(base.parents):
        if (parent / "pyproject.toml").exists():
            return parent
    return base


def get_repo_root() -> Path:
    """Return the repository root."""
    return _find_project_root(Path(__file__).resolve())


def get_package_root() -> Path:
    """Return the Python package root."""
    return Path(__file__).resolve().parents[2]


def resolve_repo_path(path: str | Path) -> Path:
    """Resolve a path relative to the repository root."""
    target = Path(path)
    if target.is_absolute():
        return target
    return (get_repo_root() / target).resolve()


def resolve_output_path(output_dir: str | Path, filename: str) -> Path:
    """Resolve a file path inside an output directory."""
    base_dir = resolve_repo_path(output_dir)
    return (base_dir / filename).resolve()


def get_prompt_path(name: str) -> str:
    """Return the absolute path to a prompt file by name."""
    return str((get_package_root() / "prompts" / name).resolve())
