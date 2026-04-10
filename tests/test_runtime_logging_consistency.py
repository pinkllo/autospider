from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "src" / "autospider"

BANNED_PATTERNS = {
    "from loguru import logger": re.compile(r"(^|\n)\s*from loguru import logger\b"),
    "traceback.print_exc()": re.compile(r"(^|\n)\s*traceback\.print_exc\("),
}


def test_runtime_code_does_not_use_banned_logging_shortcuts() -> None:
    violations: list[str] = []
    for path in SOURCE_ROOT.rglob("*.py"):
        content = path.read_text(encoding="utf-8")
        for label, pattern in BANNED_PATTERNS.items():
            if pattern.search(content):
                violations.append(f"{path.relative_to(REPO_ROOT)} -> {label}")

    assert not violations, "发现未迁移的运行时日志旁路:\n" + "\n".join(sorted(violations))
