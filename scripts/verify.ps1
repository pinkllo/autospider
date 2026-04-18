$ErrorActionPreference = "Stop"

ruff check src tests
black --check src tests
mypy src/autospider
pytest -m smoke -q
pytest tests/contracts -q

if (Get-Command lint-imports -ErrorAction SilentlyContinue) {
    lint-imports
} else {
    Write-Host "lint-imports not configured yet; skipping."
}
