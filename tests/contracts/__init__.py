from __future__ import annotations

import asyncio
import json
import re
import shutil
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator
from urllib.request import urlopen

from autospider.common.storage.idempotent_io import write_json_idempotent, write_text_if_changed
from autospider.domain.fields import FieldDefinition
from autospider.pipeline.finalization import (
    DURABILITY_STATE_DURABLE,
    build_run_record,
    classify_pipeline_result,
    commit_items_file,
    write_summary,
)
from autospider.pipeline.progress_tracker import TaskProgressTracker
from autospider.pipeline.types import PipelineRunResult

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMP_ROOT = REPO_ROOT / "artifacts" / "test_tmp" / "contracts"


@dataclass(frozen=True)
class ContractRunArtifacts:
    execution_id: str
    page_url: str
    output_dir: Path
    redis_client: Any
    result: PipelineRunResult


def normalize_help_surface(text: str) -> dict[str, Any]:
    lines = [line.rstrip() for line in text.splitlines()]
    usage = next((line.strip() for line in lines if line.strip().startswith("Usage:")), "")
    description = _first_content_line(lines, usage)
    return {
        "usage": usage,
        "description": description,
        "options": _extract_options(text),
        "commands": _extract_commands(lines),
    }


def snapshot_shape(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: snapshot_shape(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [snapshot_shape(item) for item in value]
    return type(value).__name__


def directory_files(root: Path) -> list[str]:
    return sorted(
        str(path.relative_to(root)).replace("\\", "/")
        for path in root.rglob("*")
        if path.is_file()
    )


@contextmanager
def contract_tmp_dir() -> Iterator[Path]:
    TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    path = Path(tempfile.mkdtemp(prefix="contracts-", dir=TEMP_ROOT))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def run_contract_pipeline(tmp_path: Path) -> ContractRunArtifacts:
    import fakeredis

    site_dir = _build_mock_site(tmp_path)
    execution_id = "contract-run-001"
    output_dir = tmp_path / "output" / execution_id
    redis_client = fakeredis.FakeRedis(decode_responses=True)

    with serve_site(site_dir) as page_url:
        html = _fetch_text(page_url)
        title = _mock_llm_extract_title(html)
        _seed_queue_surface(redis_client, execution_id, page_url)
        _run_async(_seed_progress(redis_client, execution_id, page_url))
        result = _finalize_contract_run(
            output_dir=output_dir,
            execution_id=execution_id,
            page_url=page_url,
            title=title,
        )

    return ContractRunArtifacts(
        execution_id=execution_id,
        page_url=page_url,
        output_dir=output_dir,
        redis_client=redis_client,
        result=result,
    )


def _first_content_line(lines: list[str], usage: str) -> str:
    for line in lines:
        text = line.strip()
        if not text or text == usage or text == "Options:" or text == "Commands:":
            continue
        return text
    return ""


def _extract_commands(lines: list[str]) -> list[str]:
    commands: list[str] = []
    in_commands = False
    for line in lines:
        stripped = line.strip()
        if stripped == "Commands:":
            in_commands = True
            continue
        if in_commands and not stripped:
            break
        if in_commands and line.startswith("  "):
            commands.append(stripped.split()[0])
    return commands


def _build_mock_site(tmp_path: Path) -> Path:
    site_dir = tmp_path / "mock_site"
    site_dir.mkdir(parents=True, exist_ok=True)
    html = "\n".join(
        [
            "<html>",
            "<body>",
            '<article data-kind="product">',
            "<h1>Contract Fixture Product</h1>",
            '<span class="price">$10</span>',
            "</article>",
            "</body>",
            "</html>",
            "",
        ]
    )
    (site_dir / "index.html").write_text(html, encoding="utf-8")
    return site_dir


@contextmanager
def serve_site(site_dir: Path) -> Iterator[str]:
    handler = _site_handler(site_dir)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/index.html"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _site_handler(site_dir: Path) -> type[SimpleHTTPRequestHandler]:
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(site_dir), **kwargs)

        def log_message(self, format: str, *args: Any) -> None:
            _ = format, args

    return Handler


def _fetch_text(url: str) -> str:
    with urlopen(url, timeout=5) as response:
        return response.read().decode("utf-8")


def _mock_llm_extract_title(html: str) -> str:
    match = re.search(r"<h1>(.*?)</h1>", html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        raise AssertionError("mock_llm_failed_to_extract_title")
    return re.sub(r"\s+", " ", match.group(1)).strip()


def _run_async(coro: Any) -> Any:
    return asyncio.run(coro)


async def _seed_progress(redis_client: Any, execution_id: str, page_url: str) -> None:
    from autospider.common.storage.pipeline_runtime_store import PipelineRuntimeStore

    tracker = TaskProgressTracker(
        execution_id,
        runtime_store=PipelineRuntimeStore(client_factory=lambda: redis_client),
    )
    await tracker.set_total(1)
    await tracker.set_runtime_state(
        {
            "stage": "collecting",
            "resume_mode": "fresh",
            "thread_id": "thread-contract-001",
            "queue": {"stream_length": 1, "pending_count": 0},
        }
    )
    await tracker.record_success(page_url)
    await tracker.mark_done("completed")


def _extract_options(text: str) -> list[str]:
    options = re.findall(r"--[a-z0-9-]+|(?<!-)-[a-z]\b", text, flags=re.IGNORECASE)
    unique: list[str] = []
    for option in options:
        if option not in unique:
            unique.append(option)
    return unique


def _seed_queue_surface(redis_client: Any, execution_id: str, page_url: str) -> None:
    key_prefix = f"autospider:urls:run:{execution_id}"
    payload = {
        "url": page_url,
        "created_at": 1710000000,
        "metadata": {"source": "contracts"},
    }
    redis_client.hset(
        f"{key_prefix}:data",
        mapping={"detail-001": json.dumps(payload, ensure_ascii=False)},
    )
    redis_client.xadd(f"{key_prefix}:stream", {"data_id": "detail-001"})


def _finalize_contract_run(
    *,
    output_dir: Path,
    execution_id: str,
    page_url: str,
    title: str,
) -> PipelineRunResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    items_path = output_dir / "pipeline_extracted_items.jsonl"
    summary_path = output_dir / "pipeline_summary.json"
    _write_planning_artifacts(output_dir, page_url)

    fields = [FieldDefinition(name="title", description="page title")]
    records = {
        page_url: build_run_record(
            url=page_url,
            item={"url": page_url, "title": title},
            success=True,
            failure_reason="",
            durability_state=DURABILITY_STATE_DURABLE,
            claim_state="acked",
        )
    }
    summary = _summary_payload(execution_id, page_url, items_path, summary_path, fields)
    summary.update(classify_pipeline_result(total_urls=1, success_count=1, state_error="", validation_failures=[]))
    summary["durability_state"] = DURABILITY_STATE_DURABLE
    summary["durably_persisted"] = True
    commit_items_file(items_path, records)
    write_summary(summary_path, summary)
    return PipelineRunResult.from_raw(summary, summary_file=str(summary_path))


def _write_planning_artifacts(output_dir: Path, page_url: str) -> None:
    write_json_idempotent(
        output_dir / "task_plan.json",
        {
            "plan_id": "contract-plan-001",
            "site_url": page_url,
            "original_request": "collect contract fixture",
            "total_subtasks": 1,
            "subtasks": [{"name": "detail", "list_url": page_url}],
        },
        identity_keys=("plan_id", "site_url"),
    )
    write_text_if_changed(
        output_dir / "plan_knowledge.md",
        "# Contract Plan\n\n- source: local-http\n- llm: mock\n",
    )


def _summary_payload(
    execution_id: str,
    page_url: str,
    items_path: Path,
    summary_path: Path,
    fields: list[FieldDefinition],
) -> dict[str, Any]:
    return {
        "run_id": execution_id,
        "execution_id": execution_id,
        "list_url": page_url,
        "task_description": "collect contract fixture",
        "mode": "redis",
        "total_urls": 1,
        "success_count": 1,
        "failed_count": 0,
        "consumer_concurrency": 1,
        "target_url_count": 1,
        "items_file": str(items_path),
        "summary_file": str(summary_path),
        "field_names": [field.name for field in fields],
        "collection_config": {"list_url": page_url, "llm_backend": "mock"},
        "extraction_config": {"fields": [field.model_dump(mode="python") for field in fields]},
        "validation_failures": [],
        "extraction_evidence": [{"url": page_url, "success": True}],
        "committed_records": [{"url": page_url, "success": True}],
        "error": "",
        "terminal_reason": "",
    }
