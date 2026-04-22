# AutoSpider

A pure-vision browser agent built on **LangGraph** and **Set-of-Mark (SoM)** prompting. Organised as a lightweight-DDD modular monolith with four Bounded Contexts, Redis as both queue and store, and a single `output/runs/<run_id>/` artifact layout.

> Status: `refactor-phase-4` (physical legacy removal) executed; `refactor-phase-5` (guardrails + verification/docs cutover) is still being tightened.

---

## Architecture at a Glance

```
autospider.interface   →   autospider.composition   →   autospider.contexts.*   →   autospider.platform
```

- **Bounded Contexts** (`src/autospider/contexts/`)
  - `chat/` — user-facing conversation & requirement capture
  - `planning/` — task planning, decomposition, replanning
  - `collection/` — browser-driven page navigation & extraction
  - `experience/` — skills, XPath patterns, feedback learning
- **Composition** (`src/autospider/composition/`) — wires contexts together: saga orchestration, event bus bindings, dependency container.
- **Interface** (`src/autospider/interface/cli/`) — Typer-based CLI: `chat-pipeline`, `resume`, `doctor`, `benchmark`.
- **Platform** (`src/autospider/platform/`) — cross-cutting infrastructure:
  - `shared_kernel/` — IDs, time, trace/run context vars
  - `observability/` — structured logging bound to `trace_id` / `run_id`
  - `persistence/` — Redis (primary) + SQL (Alembic-managed)
  - `messaging/` — ports + Redis Streams / in-memory implementations

Key architecture decisions are recorded under [`refactor/adr/`](refactor/adr/):

- [`0001-adopt-light-ddd.md`](refactor/adr/0001-adopt-light-ddd.md)
- [`0002-redis-as-queue-and-store.md`](refactor/adr/0002-redis-as-queue-and-store.md)
- [`0003-run-artifact-layout.md`](refactor/adr/0003-run-artifact-layout.md)
- [`0004-import-linter-contracts.md`](refactor/adr/0004-import-linter-contracts.md)

---

## Quick Start

```powershell
pip install -e ".[dev,redis,db]"
playwright install chromium

autospider doctor
autospider chat-pipeline -r "抓取示例站点的商品列表"
```

Runtime artifacts appear under `output/runs/<run_id>/` (see ADR 0003).

---

## Development Workflow

```powershell
# bootstrap dev tooling first
pip install -e ".[dev,redis,db]"

# lint + format + type
ruff check src tests
black --check src tests
mypy src/autospider

# layered architecture contracts
lint-imports

# preferred local verification entrypoint
scripts/verify.ps1

# pre-commit hooks
pre-commit run --all-files

# tests
pytest -m smoke -q
pytest tests/contracts -q
pytest tests/contexts tests/platform tests/composition tests/interface -q
```

`scripts/_gate_file_size.py` blocks new `.py` files beyond 500 lines (tests and prompts exempt).
If `.importlinter` exists but `lint-imports` is missing, `scripts/verify.ps1` / `scripts/verify.sh` now fail fast instead of silently skipping architecture checks.

---

## Testing Layout

- `tests/contracts/` — end-to-end snapshot safety net (CLI surface, Redis key registry, output layout, result envelope). **Must not drift without an ADR.**
- `tests/contexts/` — domain + application unit tests per Bounded Context.
- `tests/platform/` — shared kernel, observability, persistence, messaging.
- `tests/composition/` — cross-context wiring, event propagation.
- `tests/interface/` — CLI smoke tests.
- `tests/e2e/` — full-stack tests (Redis + PostgreSQL + Playwright required, gated by `.env.e2e`).
- `tests/benchmark/` — benchmark scenarios and mock site.
- `tests/integration/` — infrastructure-bound tests requiring live Redis / PostgreSQL.

---

## Further Reading

- [`AGENTS.md`](AGENTS.md) — repository guidelines for contributors and agents.
- [`refactor/`](refactor/) — archived refactor plan (phase 0–5) and ADRs.
- [`refactor/05-guardrails.md`](refactor/05-guardrails.md) — `ruff` / `mypy` / `import-linter` / `pre-commit` / CI configuration reference.
