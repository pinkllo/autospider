from __future__ import annotations

import importlib
import json
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest

pytestmark = pytest.mark.smoke

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def _reload_trace_module():
    config_module = importlib.import_module("autospider.platform.config.runtime")
    trace_logger = importlib.import_module("autospider.platform.llm.trace_logger")

    config_module.get_config(reload=True)
    return importlib.reload(trace_logger)


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


@pytest.fixture()
def repo_tmp_dir() -> Path:
    path = Path(tempfile.mkdtemp(prefix="trace-tests-"))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def test_append_llm_trace_appends_jsonl_records(
    monkeypatch: pytest.MonkeyPatch,
    repo_tmp_dir: Path,
) -> None:
    trace_path = repo_tmp_dir / "llm-trace.jsonl"
    monkeypatch.setenv("LLM_TRACE_ENABLED", "true")
    monkeypatch.setenv("LLM_TRACE_FILE", str(trace_path))
    trace_logger = _reload_trace_module()

    trace_logger.append_llm_trace(
        "planner",
        {"model": "gpt-test", "input": "first", "output": "one", "response_summary": "alpha"},
    )
    trace_logger.append_llm_trace(
        "planner",
        {"model": "gpt-test", "input": "second", "output": "two", "response_summary": "beta"},
    )

    records = _read_jsonl(trace_path)
    assert len(records) == 2
    assert records[0]["input"] == "first"
    assert records[0]["output"] == "one"
    assert records[1]["input"] == "second"
    assert records[1]["response_summary"] == "beta"


def test_append_llm_trace_writes_real_timestamp(
    monkeypatch: pytest.MonkeyPatch,
    repo_tmp_dir: Path,
) -> None:
    trace_path = repo_tmp_dir / "llm-trace-timestamp.jsonl"
    monkeypatch.setenv("LLM_TRACE_ENABLED", "true")
    monkeypatch.setenv("LLM_TRACE_FILE", str(trace_path))
    trace_logger = _reload_trace_module()

    trace_logger.append_llm_trace(
        "collector",
        {"model": "gpt-test", "input": "ping", "output": "pong", "response_summary": "ok"},
    )

    record = _read_jsonl(trace_path)[0]
    timestamp = str(record["timestamp"])
    assert timestamp
    datetime.fromisoformat(timestamp.replace("Z", "+00:00"))


def test_append_llm_trace_resolves_relative_paths_from_repo_root(
    monkeypatch: pytest.MonkeyPatch,
    repo_tmp_dir: Path,
) -> None:
    relative_path = Path("output/__pytest__") / f"trace-{uuid4().hex}.jsonl"
    repo_target = (REPO_ROOT / relative_path).resolve()
    cwd_target = (repo_tmp_dir / relative_path).resolve()
    monkeypatch.chdir(repo_tmp_dir)
    monkeypatch.setenv("LLM_TRACE_ENABLED", "true")
    monkeypatch.setenv("LLM_TRACE_FILE", str(relative_path))
    trace_logger = _reload_trace_module()

    try:
        trace_logger.append_llm_trace(
            "field",
            {"model": "gpt-test", "input": "a", "output": "b", "response_summary": "c"},
        )
        assert repo_target.exists()
        assert not cwd_target.exists()
    finally:
        repo_target.unlink(missing_ok=True)
        cwd_target.unlink(missing_ok=True)
