"""Fail pre-commit if a staged .py file exceeds 500 lines (excluding tests)."""

from __future__ import annotations

import sys
from pathlib import Path

LIMIT = 500
EXEMPT_PREFIX = ("tests/", "src/autospider/prompts/", "src/autospider/legacy/")


def _count_lines(path: Path) -> int:
    return sum(1 for _ in path.open(encoding="utf-8", errors="ignore"))


def main(paths: list[str]) -> int:
    failed: list[tuple[str, int]] = []
    for raw in paths:
        normalized = raw.replace("\\", "/")
        if not normalized.endswith(".py"):
            continue
        if any(normalized.startswith(prefix) for prefix in EXEMPT_PREFIX):
            continue
        path = Path(raw)
        if not path.exists():
            continue
        n = _count_lines(path)
        if n > LIMIT:
            failed.append((normalized, n))

    if failed:
        for p, n in failed:
            print(f"[file-size-gate] {p} has {n} lines (limit {LIMIT}). Please split.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
