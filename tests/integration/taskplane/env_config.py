from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv

REDIS_ENV_KEYS = ("AUTOSPIDER_TASKPLANE_REDIS_URL", "AUTOSPIDER_E2E_REDIS_URL", "GRAPH_REDIS_URL")
DATABASE_ENV_KEYS = (
    "AUTOSPIDER_TASKPLANE_DATABASE_URL",
    "AUTOSPIDER_E2E_DATABASE_URL",
    "DATABASE_URL",
)
DEFAULT_GRAPH_REDIS_HOST = "localhost"
DEFAULT_GRAPH_REDIS_PORT = "6379"
DEFAULT_GRAPH_REDIS_DB = "1"


def load_taskplane_dotenv(start_path: Path | None = None) -> None:
    for dotenv_path in _dotenv_candidates(start_path or Path(__file__).resolve()):
        load_dotenv(dotenv_path, override=False)


def resolve_taskplane_database_url(env: dict[str, str] | None = None) -> str:
    return _normalize_database_url(_first_env(DATABASE_ENV_KEYS, env))


def resolve_taskplane_redis_url(env: dict[str, str] | None = None) -> str:
    redis_url = _first_env(REDIS_ENV_KEYS, env)
    if redis_url:
        return redis_url
    return _build_graph_redis_url(env)


def _first_env(keys: tuple[str, ...], env: dict[str, str] | None) -> str:
    source = env or os.environ
    for key in keys:
        value = str(source.get(key) or "").strip()
        if value:
            return value
    return ""


def _build_graph_redis_url(env: dict[str, str] | None) -> str:
    source = env or os.environ
    host = str(source.get("GRAPH_REDIS_HOST") or DEFAULT_GRAPH_REDIS_HOST).strip()
    port = str(source.get("GRAPH_REDIS_PORT") or DEFAULT_GRAPH_REDIS_PORT).strip()
    db = str(source.get("GRAPH_REDIS_DB") or DEFAULT_GRAPH_REDIS_DB).strip()
    password = str(source.get("GRAPH_REDIS_PASSWORD") or "").strip()
    if not any(
        source.get(key)
        for key in (
            "GRAPH_REDIS_HOST",
            "GRAPH_REDIS_PORT",
            "GRAPH_REDIS_DB",
            "GRAPH_REDIS_PASSWORD",
        )
    ):
        return ""
    auth = f":{quote(password, safe='')}@" if password else ""
    return f"redis://{auth}{host}:{port}/{db}"


def _repo_root(path: Path) -> Path:
    if path.is_file():
        path = path.parent
    return path.parents[2]


def _dotenv_candidates(start_path: str | Path) -> list[Path]:
    repo_root = _repo_root(Path(start_path))
    candidates = [repo_root / ".env"]
    parent_dir = repo_root.parent
    if parent_dir.name in {".worktrees", "worktrees"}:
        candidates.append(parent_dir.parent / ".env")
    return candidates


def _normalize_database_url(url: str) -> str:
    parsed = urlsplit(url)
    scheme = str(parsed.scheme or "").strip().lower()
    if scheme in {"postgresql", "postgresql+psycopg2"}:
        return urlunsplit(
            ("postgresql+psycopg", parsed.netloc, parsed.path, parsed.query, parsed.fragment)
        )
    return url
