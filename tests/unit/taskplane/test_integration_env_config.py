from tests.integration.taskplane.env_config import (
    _dotenv_candidates,
    _normalize_database_url,
    resolve_taskplane_database_url,
    resolve_taskplane_redis_url,
)


def test_database_url_falls_back_to_database_url_env() -> None:
    env = {"DATABASE_URL": "postgresql+psycopg2://postgres:postgres@localhost:5432/autospider"}
    assert (
        resolve_taskplane_database_url(env)
        == "postgresql+psycopg://postgres:postgres@localhost:5432/autospider"
    )


def test_redis_url_falls_back_to_graph_redis_url_env() -> None:
    env = {"GRAPH_REDIS_URL": "redis://localhost:6379/1"}
    assert resolve_taskplane_redis_url(env) == "redis://localhost:6379/1"


def test_redis_url_builds_from_graph_redis_parts() -> None:
    env = {
        "GRAPH_REDIS_HOST": "127.0.0.1",
        "GRAPH_REDIS_PORT": "6380",
        "GRAPH_REDIS_PASSWORD": "secret",
        "GRAPH_REDIS_DB": "15",
    }
    assert resolve_taskplane_redis_url(env) == "redis://:secret@127.0.0.1:6380/15"


def test_dotenv_candidates_include_project_root_for_worktree_path() -> None:
    candidates = _dotenv_candidates(
        r"D:\autospider\.worktrees\taskplane-2026-04-14\tests\integration\taskplane\env_config.py"
    )
    assert str(candidates[0]).endswith(r".worktrees\taskplane-2026-04-14\.env")
    assert str(candidates[1]).endswith(r"D:\autospider\.env")


def test_normalize_database_url_converts_psycopg2_to_psycopg() -> None:
    url = "postgresql+psycopg2://postgres:postgres@localhost:5432/autospider"
    assert (
        _normalize_database_url(url)
        == "postgresql+psycopg://postgres:postgres@localhost:5432/autospider"
    )
