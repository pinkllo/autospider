from pathlib import Path
import sys

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autospider.legacy.common.db.engine import _normalize_database_url


def test_normalize_database_url_prefers_psycopg_for_plain_postgresql() -> None:
    assert _normalize_database_url("postgresql://u:p@localhost:5432/db") == (
        "postgresql+psycopg://u:p@localhost:5432/db"
    )


def test_normalize_database_url_keeps_explicit_psycopg() -> None:
    assert _normalize_database_url("postgresql+psycopg://u:p@localhost:5432/db") == (
        "postgresql+psycopg://u:p@localhost:5432/db"
    )


def test_normalize_database_url_keeps_explicit_psycopg2() -> None:
    assert _normalize_database_url("postgresql+psycopg2://u:p@localhost:5432/db") == (
        "postgresql+psycopg2://u:p@localhost:5432/db"
    )


def test_normalize_database_url_keeps_sqlite() -> None:
    assert _normalize_database_url("sqlite:///tmp/test.db") == "sqlite:///tmp/test.db"
