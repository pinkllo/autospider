from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

EXPECTED_TABLES = {
    "ch_sessions",
    "cl_field_xpaths",
    "cl_page_results",
    "cl_runs",
    "ex_skill_usages",
    "ex_skills",
    "pl_failure_signals",
    "pl_plans",
    "pl_subtasks",
}
WORKSPACE_DIR = Path(__file__).resolve().parents[4] / ".tmp" / "alembic-tests"


def test_alembic_upgrade_head_creates_phase1_tables() -> None:
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    database_path = WORKSPACE_DIR / "phase1.sqlite3"
    database_path.unlink(missing_ok=True)
    config = Config(str(Path("alembic.ini").resolve()))
    config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{database_path}")

    command.upgrade(config, "head")

    engine = create_engine(f"sqlite+pysqlite:///{database_path}", future=True)
    tables = set(inspect(engine).get_table_names())

    assert EXPECTED_TABLES.issubset(tables)
