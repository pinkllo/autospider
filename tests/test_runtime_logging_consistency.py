from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.smoke

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "src" / "autospider"

BANNED_PATTERNS = {
    "from loguru import logger": re.compile(r"(^|\n)\s*from loguru import logger\b"),
    "traceback.print_exc()": re.compile(r"(^|\n)\s*traceback\.print_exc\("),
}


def _format_violation(*, path: Path, line_no: int, pattern_label: str, snippet: str) -> str:
    relative_path = path.relative_to(REPO_ROOT).as_posix()
    return f"{relative_path}:{line_no} -> {pattern_label} -> {snippet.strip()}"


def _collect_violations(*, source_root: Path) -> list[str]:
    violations: list[str] = []
    for path in source_root.rglob("*.py"):
        lines = path.read_text(encoding="utf-8").splitlines()
        for line_no, line in enumerate(lines, start=1):
            for label, pattern in BANNED_PATTERNS.items():
                if pattern.search(line):
                    violations.append(
                        _format_violation(
                            path=path,
                            line_no=line_no,
                            pattern_label=label,
                            snippet=line,
                        )
                    )
    return sorted(violations)


def test_format_violation_includes_path_line_pattern_and_snippet() -> None:
    rendered = _format_violation(
        path=REPO_ROOT / "src" / "autospider" / "example.py",
        line_no=7,
        pattern_label="traceback.print_exc()",
        snippet="traceback.print_exc()",
    )

    assert (
        rendered == "src/autospider/example.py:7 -> traceback.print_exc() -> traceback.print_exc()"
    )


def test_runtime_code_does_not_use_banned_logging_shortcuts() -> None:
    violations = _collect_violations(source_root=SOURCE_ROOT)
    violation_summary = "\n".join(sorted(violations))
    assert not violations, f"发现 {len(violations)} 处未迁移的运行时日志旁路:\n{violation_summary}"
