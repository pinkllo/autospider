#!/usr/bin/env bash
set -euo pipefail

ruff check src tests
black --check src tests
mypy src/autospider
pytest -m smoke -q
pytest tests/contracts -q

if command -v lint-imports >/dev/null 2>&1; then
  lint-imports
else
  printf '%s\n' "lint-imports not configured yet; skipping."
fi
