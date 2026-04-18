#!/usr/bin/env bash
set -euo pipefail

run_pytest_with_timeout() {
  if ! command -v timeout >/dev/null 2>&1; then
    printf '%s\n' "timeout command is required for verify.sh"
    exit 1
  fi
  timeout 60s pytest "$@"
}

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

ruff check src tests
black --check src tests
mypy src/autospider
run_pytest_with_timeout -m smoke -q
run_pytest_with_timeout tests/contracts -q

if command -v lint-imports >/dev/null 2>&1 && [ -f ".importlinter" ]; then
  lint-imports
else
  printf '%s\n' "lint-imports skipped: command missing or .importlinter not found."
fi
