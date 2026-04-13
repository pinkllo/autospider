# Repository Guidelines

## Project Structure & Module Organization
Core code lives in `src/autospider/`. Keep new modules close to their responsibility: `graph/` for LangGraph orchestration, `pipeline/` for subtask execution, `crawler/` for collection and planning, `field/` for extraction/XPath logic, and `common/` for shared infrastructure. Prompt templates live in `src/autospider/prompts/`. Tests are under `tests/`, with end-to-end coverage in `tests/e2e/`. Runtime artifacts belong in `output/`, temporary E2E files in `.tmp/e2e-runtime/`, and browser auth state in `.auth/`.

## Build, Test, and Development Commands
Install locally with `pip install -e .` and add dev tooling via `pip install -e ".[dev]"`. Install browser binaries with `playwright install chromium`.

- `autospider doctor`: validate local runtime prerequisites.
- `autospider chat-pipeline -r "<request>"`: run the main planning-first collection flow.
- `autospider resume --thread-id "<id>"`: resume an interrupted LangGraph run.
- `pytest -m smoke -q`: fast developer checks.
- `pytest tests/e2e -m e2e -q`: maintained E2E entrypoint.
- `ruff check src tests && black --check src tests && mypy src/autospider`: lint, format, and type-check before opening a PR.

## Coding Style & Naming Conventions
Target Python 3.10, 4-space indentation, and a 100-character line limit (`ruff` and `black` enforce this). Use type hints on public functions and keep modules focused by responsibility. Follow existing naming: `snake_case` for files, functions, and variables; `PascalCase` for classes; test files like `test_pipeline_finalization.py`. Prefer explicit dependency injection over hidden globals, and keep CLI behavior in `cli.py` or `cli_runtime.py`.

## Testing Guidelines
Use `pytest` with `pytest-asyncio`; mark async tests with `@pytest.mark.asyncio`. Place unit tests next to the behavior they cover using `test_<feature>.py`. When changing graph, pipeline, Redis, or CLI flows, update smoke tests first and run the E2E command if the change crosses system boundaries. E2E relies on `.env.e2e`, PostgreSQL, Redis, and Playwright; unavailable infra should surface as explicit skips, not silent fallbacks.

## Commit & Pull Request Guidelines
Match the repository’s Conventional Commit style: `feat: ...`, `fix: ...`, `docs: ...`, `refactor(scope): ...`. Keep subjects short and imperative; optional scopes should reflect the touched subsystem, for example `refactor(channel): ...`. PRs should state the behavioral change, list verification commands run, link the related issue or task, and include screenshots only when CLI behavior changed.

## Security & Configuration Tips
Start from `.env.example`; keep secrets only in `.env` or `.env.e2e` files and never commit them. Treat Redis/PostgreSQL settings as environment-specific. Do not check in generated output, auth snapshots, or temporary runtime files unless a test fixture explicitly requires them.
