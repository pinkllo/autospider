from __future__ import annotations

import re
from pathlib import Path

from packaging.requirements import Requirement

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
UV_LOCK_PATH = REPO_ROOT / "uv.lock"


def _load_dev_dependency_names() -> list[str]:
    lines = PYPROJECT_PATH.read_text(encoding="utf-8").splitlines()
    in_optional_dependencies = False
    in_dev_block = False
    dependencies: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("["):
            in_optional_dependencies = stripped == "[project.optional-dependencies]"
            in_dev_block = False
            continue
        if not in_optional_dependencies:
            continue
        if not in_dev_block and stripped.startswith("dev = ["):
            in_dev_block = True
            continue
        if in_dev_block and stripped == "]":
            break
        if not in_dev_block:
            continue
        match = re.search(r'"([^"]+)"', stripped)
        if match is None:
            continue
        dependencies.append(Requirement(match.group(1)).name)
    return dependencies


def _load_uv_lock_package_names() -> set[str]:
    text = UV_LOCK_PATH.read_text(encoding="utf-8")
    return set(re.findall(r'^name = "([^"]+)"$', text, flags=re.MULTILINE))


def test_uv_lock_covers_pyproject_dev_dependencies() -> None:
    dev_dependencies = _load_dev_dependency_names()
    lock_packages = _load_uv_lock_package_names()

    assert dev_dependencies
    assert not sorted(set(dev_dependencies) - lock_packages)
