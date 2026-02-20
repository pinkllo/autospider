from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from autospider.common.config import config
from autospider.common.llm.trace_logger import append_llm_trace


def _new_trace_path() -> Path:
    output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / f"llm_trace_test_{uuid4().hex}.json"


def test_append_llm_trace_writes_json_array(monkeypatch):
    trace_path = _new_trace_path()

    monkeypatch.setattr(config.llm, "trace_enabled", True)
    monkeypatch.setattr(config.llm, "trace_file", str(trace_path))
    monkeypatch.setattr(config.llm, "trace_max_chars", 20000)

    try:
        append_llm_trace("decider", {"input": {"k": "v"}})
        append_llm_trace("task_clarifier", {"output": {"ok": True}})

        content = trace_path.read_text(encoding="utf-8")
        data = json.loads(content)

        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["component"] == "decider"
        assert data[1]["component"] == "task_clarifier"
    finally:
        trace_path.unlink(missing_ok=True)


def test_append_llm_trace_migrates_legacy_jsonl(monkeypatch):
    trace_path = _new_trace_path()
    trace_path.write_text(
        '{"component":"old_a","payload":{"id":1}}\n{"component":"old_b","payload":{"id":2}}\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(config.llm, "trace_enabled", True)
    monkeypatch.setattr(config.llm, "trace_file", str(trace_path))
    monkeypatch.setattr(config.llm, "trace_max_chars", 20000)

    try:
        append_llm_trace("decider", {"input": {"migrated": True}})

        content = trace_path.read_text(encoding="utf-8")
        data = json.loads(content)

        assert isinstance(data, list)
        assert len(data) == 3
        assert data[0]["component"] == "old_a"
        assert data[1]["component"] == "old_b"
        assert data[2]["component"] == "decider"
    finally:
        trace_path.unlink(missing_ok=True)
