from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

_REDIS_BOOT_TIMEOUT_S = 5.0
_REDIS_DB_INDEX = 15


@dataclass(frozen=True, slots=True)
class E2ERuntime:
    workspace: Path
    output_root: Path
    redis_url: str
    redis_process: subprocess.Popen[str] | None = None


def prepare_e2e_runtime(workspace: Path) -> E2ERuntime:
    repo_root = Path(__file__).resolve().parents[2]
    load_dotenv(repo_root / ".env.e2e", override=False)

    database_url = str(os.getenv("AUTOSPIDER_E2E_DATABASE_URL") or "").strip()
    if not database_url:
        raise RuntimeError("缺少 AUTOSPIDER_E2E_DATABASE_URL")
    if not _has_llm_credentials():
        raise RuntimeError("缺少 LLM API 凭证（BAILIAN_API_KEY 或 SILICON_PLANNER_API_KEY）")

    output_root = workspace / "output"
    output_root.mkdir(parents=True, exist_ok=True)

    redis_url, redis_process = _resolve_redis_runtime()
    _apply_e2e_env(database_url=database_url, redis_url=redis_url, output_root=output_root)
    _reload_runtime_config()
    reset_e2e_state()
    return E2ERuntime(
        workspace=workspace,
        output_root=output_root,
        redis_url=redis_url,
        redis_process=redis_process,
    )


def teardown_e2e_runtime(runtime: E2ERuntime) -> None:
    try:
        _close_db()
    finally:
        process = runtime.redis_process
        if process is None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def reset_e2e_state() -> None:
    _flush_checkpoint_redis()
    _close_db()
    _reload_runtime_config()
    _init_db(reset=True)


def build_case_output_dir(*, output_root: Path, node_id: str) -> Path:
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(node_id or "case")).strip("._")
    resolved = output_root / (safe_name or "case")
    if resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _has_llm_credentials() -> bool:
    return bool(
        str(os.getenv("BAILIAN_API_KEY") or "").strip()
        or str(os.getenv("SILICON_PLANNER_API_KEY") or "").strip()
    )


def _resolve_redis_runtime() -> tuple[str, subprocess.Popen[str] | None]:
    explicit = str(os.getenv("AUTOSPIDER_E2E_REDIS_URL") or "").strip()
    if explicit:
        return explicit, None

    redis_server = shutil.which("redis-server")
    if not redis_server:
        raise RuntimeError("缺少 AUTOSPIDER_E2E_REDIS_URL，且 PATH 中找不到 redis-server")

    port = _allocate_local_port()
    process = subprocess.Popen(
        [
            redis_server,
            "--save",
            "",
            "--appendonly",
            "no",
            "--port",
            str(port),
            "--databases",
            str(_REDIS_DB_INDEX + 1),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    _wait_for_tcp_ready(host="127.0.0.1", port=port, timeout_s=_REDIS_BOOT_TIMEOUT_S)
    return f"redis://127.0.0.1:{port}/{_REDIS_DB_INDEX}", process


def _allocate_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_tcp_ready(*, host: str, port: int, timeout_s: float) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            try:
                sock.connect((host, port))
                return
            except OSError:
                time.sleep(0.1)
    raise RuntimeError(f"临时 redis-server 未能在 {timeout_s:.1f}s 内启动: {host}:{port}")


def _apply_e2e_env(*, database_url: str, redis_url: str, output_root: Path) -> None:
    os.environ["DATABASE_URL"] = database_url
    os.environ["GRAPH_CHECKPOINT_ENABLED"] = "true"
    os.environ["GRAPH_CHECKPOINT_BACKEND"] = "redis"
    os.environ["GRAPH_REDIS_URL"] = redis_url
    os.environ["PIPELINE_MODE"] = "memory"
    os.environ["HEADLESS"] = "true"
    os.environ["AUTOSPIDER_E2E_OUTPUT_ROOT"] = str(output_root)


def _reload_runtime_config() -> None:
    from autospider.common.config import get_config

    get_config(reload=True)


def _close_db() -> None:
    from autospider.common.db.engine import close_db

    close_db()


def _init_db(*, reset: bool) -> None:
    from autospider.common.db.engine import init_db

    init_db(reset=reset)


def _flush_checkpoint_redis() -> None:
    redis_url = str(os.getenv("GRAPH_REDIS_URL") or os.getenv("AUTOSPIDER_E2E_REDIS_URL") or "").strip()
    if not redis_url:
        return
    parsed = urlparse(redis_url)
    if not parsed.scheme.startswith("redis"):
        raise RuntimeError(f"不支持的 Redis URL: {redis_url}")

    try:
        import redis
    except ImportError as exc:
        raise RuntimeError("缺少 redis 依赖，无法清理 E2E checkpoint 状态") from exc

    client = redis.Redis.from_url(redis_url)
    try:
        client.ping()
        client.flushdb()
    finally:
        client.close()
