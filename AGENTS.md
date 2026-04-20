# Repository Guidelines

## Project Structure & Module Organization
Core code lives in `src/autospider/` and follows the Bounded Context layout introduced in the refactor (see `refactor/adr/0001-adopt-light-ddd.md`):

- `contexts/{chat,planning,collection,experience}/{domain,application,infrastructure}/` — Bounded Contexts with domain-pure `domain/`, use-case-driven `application/`, and adapter-heavy `infrastructure/`.
- `composition/` — wires contexts together (saga, event bus bindings, container).
- `interface/cli/` — Typer CLI entry points (`chat_pipeline`, `resume`, `doctor`, `benchmark`).
- `platform/{shared_kernel,observability,persistence,messaging}/` — cross-cutting infrastructure (IDs, logging, Redis/SQL adapters, messaging ports).
- `platform/persistence/redis/keys.py` — centralized Redis key registry (`v1:` prefix required, see `refactor/adr/0002-redis-as-queue-and-store.md`).
- `legacy/` — phase-4 residual modules retained until full deletion; no new code goes here.
- `prompts/` — LLM prompt templates (YAML assets).

Tests are under `tests/{contexts,composition,platform,interface,contracts,e2e,benchmark,integration,unit}/`. Runtime artifacts land under `output/runs/<run_id>/` per `refactor/adr/0003-run-artifact-layout.md`.

## Build, Test, and Development Commands
Install locally with `pip install -e ".[dev,redis,db]"` and browser binaries via `playwright install chromium`.

- `autospider doctor`: validate local runtime prerequisites.
- `autospider chat-pipeline -r "<request>"`: planning-first collection flow.
- `autospider resume --thread-id "<id>"`: resume an interrupted LangGraph run.
- `pytest -m smoke -q`: fast developer checks.
- `pytest tests/contracts -q`: contract snapshot suite (must not drift).
- `pytest tests/e2e -m e2e -q`: maintained E2E entry point (Redis + PostgreSQL + Playwright required).
- `ruff check src tests && black --check src tests && mypy src/autospider`: lint, format, and type-check before opening a PR.
- `lint-imports`: enforce layered architecture contracts from `.importlinter` (see `refactor/adr/0004-import-linter-contracts.md`).
- `pre-commit run --all-files`: run the full hook suite locally.

## Coding Style & Naming Conventions
Target Python 3.10, 4-space indentation, 100-character line limit (`ruff` + `black` enforce). Absolute imports only (`ban-relative-imports = all`). Use type hints on all public functions; `domain/` and `platform.shared_kernel/` are typed in mypy `strict` mode. Naming: `snake_case` for files, functions, variables; `PascalCase` for classes; test files like `test_pipeline_finalization.py`. Prefer explicit dependency injection over module-level singletons, and keep CLI behavior in `interface/cli/`.

## Testing Guidelines
Use `pytest` with `pytest-asyncio`; mark async tests with `@pytest.mark.asyncio`. Place unit tests next to the behavior they cover using `test_<feature>.py`. When changing graph, pipeline, Redis, or CLI flows, update smoke and contract tests first, then run `tests/e2e` if the change crosses system boundaries. E2E relies on `.env.e2e`, PostgreSQL, Redis, and Playwright; unavailable infra should surface as explicit skips, not silent fallbacks.

## Commit & Pull Request Guidelines
Match the repository’s Conventional Commit style: `feat: ...`, `fix: ...`, `docs: ...`, `refactor(scope): ...`, `chore(ci): ...`. Keep subjects short and imperative; optional scopes should reflect the touched subsystem, for example `refactor(channel): ...`. PRs should state the behavioral change, list verification commands run, link the related issue or task, include screenshots only when CLI behavior changed, and reference the relevant ADR when architecture is touched (`refactor/adr/NNNN-*.md`). The PR template lives at `.github/pull_request_template.md`.

## Security & Configuration Tips
Start from `.env.example`; keep secrets only in `.env` or `.env.e2e` files and never commit them. Treat Redis/PostgreSQL settings as environment-specific. Do not check in generated output, auth snapshots, or temporary runtime files unless a test fixture explicitly requires them.
