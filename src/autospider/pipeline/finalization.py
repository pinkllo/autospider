"""Pipeline finalization helpers."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable
from urllib.parse import urlparse

import yaml

from ..common.logger import get_logger
from ..common.storage.idempotent_io import write_json_idempotent, write_text_if_changed

if TYPE_CHECKING:
    from ..domain.fields import FieldDefinition
    from .orchestration import PipelineSessionBundle
    from .progress_tracker import TaskProgressTracker

logger = get_logger(__name__)


def _is_valid_xpath(xpath: object) -> bool:
    return isinstance(xpath, str) and xpath.strip().startswith("/")


def prepare_fields_config(
    fields_config: list[dict],
) -> tuple[list[dict], list[str], list[str]]:
    valid_fields: list[dict] = []
    missing_required: list[str] = []
    missing_optional: list[str] = []

    for field in fields_config:
        if not isinstance(field, dict):
            continue

        field_name = str(field.get("name") or "").strip() or "<unknown>"
        xpath = field.get("xpath")
        required = bool(field.get("required", True))
        data_type = str(field.get("data_type") or "").strip().lower()
        source = str(field.get("extraction_source") or "").strip().lower()
        fixed_value = field.get("fixed_value")

        if _is_valid_xpath(xpath):
            normalized = dict(field)
            normalized["xpath"] = str(xpath).strip()
            valid_fields.append(normalized)
            continue

        if source in {"constant", "subtask_context"}:
            value = "" if fixed_value is None else str(fixed_value).strip()
            if value:
                normalized = dict(field)
                normalized["xpath"] = None
                normalized["extraction_source"] = source
                normalized["fixed_value"] = value
                valid_fields.append(normalized)
                continue

        if data_type == "url":
            normalized = dict(field)
            normalized["xpath"] = None
            normalized["extraction_source"] = "task_url"
            valid_fields.append(normalized)
            continue

        if required:
            missing_required.append(field_name)
        else:
            missing_optional.append(field_name)

    return valid_fields, missing_required, missing_optional


def find_output_draft_skill(list_url: str, output_dir: str) -> tuple[str, Path] | None:
    domain = urlparse(str(list_url or "")).netloc.strip().lower()
    if not domain:
        return None

    output_path = Path(output_dir)
    candidates = [
        output_path / "draft_skills" / domain / "SKILL.md",
        output_path.parent / "draft_skills" / domain / "SKILL.md",
    ]
    for candidate in candidates:
        if candidate.exists():
            return domain, candidate
    return None


def cleanup_output_draft_skill(list_url: str, output_dir: str) -> None:
    located = find_output_draft_skill(list_url, output_dir)
    if located is None:
        return

    _, draft_path = located
    try:
        draft_path.unlink(missing_ok=True)
        logger.info("[Pipeline] 已清理输出目录中的 Draft Skill: %s", draft_path)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[Pipeline] 清理 Draft Skill 失败（不影响主流程）: %s", exc)


def load_validation_failures(output_path: Path) -> list[dict]:
    detail_path = output_path / "extraction_result.json"
    if not detail_path.exists():
        return []
    try:
        payload = json.loads(detail_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    failures = payload.get("validation_failures", [])
    return list(failures) if isinstance(failures, list) else []


def classify_pipeline_result(
    *,
    total_urls: int,
    success_count: int,
    state_error: object,
    validation_failures: list[dict],
) -> dict[str, object]:
    failed_count = max(total_urls - success_count, 0)
    success_rate = (success_count / total_urls) if total_urls > 0 else 0.0
    validation_failure_count = len(validation_failures)
    execution_state = "failed" if state_error else "completed"

    if success_count <= 0 or total_urls <= 0:
        outcome_state = "failed"
    elif not state_error and success_rate > 0.7 and validation_failure_count == 0:
        outcome_state = "success"
    else:
        outcome_state = "partial_success"

    if (
        total_urls > 0
        and success_count > 0
        and not state_error
        and success_rate > 0.7
        and validation_failure_count == 0
    ):
        promotion_state = "reusable"
    elif success_count > 0:
        promotion_state = "diagnostic_only"
    else:
        promotion_state = "rejected"

    return {
        "execution_state": execution_state,
        "outcome_state": outcome_state,
        "promotion_state": promotion_state,
        "success_rate": round(success_rate, 4),
        "failed_count": failed_count,
        "required_field_success_rate": round(success_rate, 4),
        "validation_failure_count": validation_failure_count,
    }


def should_promote_skill(
    *,
    state: dict[str, object],
    summary: dict,
    validation_failures: list[dict],
) -> bool:
    if str(summary.get("promotion_state") or "").strip().lower() == "reusable":
        return True

    classified = classify_pipeline_result(
        total_urls=int(summary.get("total_urls", 0) or 0),
        success_count=int(summary.get("success_count", 0) or 0),
        state_error=state.get("error"),
        validation_failures=validation_failures,
    )
    return bool(classified.get("promotion_state") == "reusable")


def strip_draft_markers_from_skill_content(content: str) -> str:
    text = str(content or "")
    if not text.strip():
        return text

    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                frontmatter = yaml.safe_load(parts[1]) or {}
            except Exception:
                frontmatter = None
            if isinstance(frontmatter, dict):
                description = str(frontmatter.get("description") or "").strip()
                if description:
                    frontmatter["description"] = (
                        description.replace("（草稿）", "").replace("草稿", "").strip()
                    )
                rendered = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip()
                text = f"---\n{rendered}\n---{parts[2]}"

    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line
        if line.startswith("# ") and "（草稿）" in line:
            line = line.replace("（草稿）", "")
        if line.startswith("- **状态**:") and ("draft" in line.lower() or "草稿" in line):
            continue
        lines.append(line)

    cleaned = "\n".join(lines).strip()
    if cleaned:
        cleaned += "\n"
    return cleaned


def build_execution_id(
    *,
    list_url: str,
    task_description: str,
    fields: list["FieldDefinition"],
    target_url_count: int | None,
    max_pages: int | None,
    pipeline_mode: str | None,
    thread_id: str,
) -> str:
    payload = {
        "list_url": list_url,
        "task_description": task_description,
        "fields": [field.model_dump(mode="python") for field in fields],
        "target_url_count": target_url_count,
        "max_pages": max_pages,
        "pipeline_mode": pipeline_mode,
        "thread_id": thread_id,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def prepare_pipeline_workspace(
    *,
    output_path: Path,
    staging_dir: Path,
    items_path: Path,
    summary_path: Path,
    manifest_path: Path,
    execution_id: str,
    list_url: str,
    task_description: str,
) -> None:
    previous_execution_id = ""
    if manifest_path.exists():
        try:
            previous_execution_id = str(
                json.loads(manifest_path.read_text(encoding="utf-8")).get("execution_id") or ""
            )
        except Exception:
            previous_execution_id = ""

    if previous_execution_id and previous_execution_id != execution_id:
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        if items_path.exists():
            items_path.unlink(missing_ok=True)
        if summary_path.exists():
            summary_path.unlink(missing_ok=True)

    output_path.mkdir(parents=True, exist_ok=True)
    staging_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "execution_id": execution_id,
        "list_url": list_url,
        "task_description": task_description,
        "updated_at": "",
    }
    write_json_idempotent(
        manifest_path,
        manifest,
        identity_keys=("execution_id", "list_url", "task_description"),
    )


def staged_record_path(staging_dir: Path, url: str) -> Path:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return staging_dir / f"{digest}.json"


def build_staged_record(
    *,
    url: str,
    item: dict,
    success: bool,
    failure_reason: str,
) -> dict:
    return {
        "url": url,
        "success": bool(success),
        "failure_reason": str(failure_reason or ""),
        "item": dict(item),
    }


def write_staged_record(staging_dir: Path, record: dict) -> None:
    path = staged_record_path(staging_dir, str(record.get("url") or ""))
    write_json_atomic(path, record)


def load_staged_records(staging_dir: Path) -> dict[str, dict]:
    if not staging_dir.exists():
        return {}

    records: dict[str, dict] = {}
    for record_file in sorted(staging_dir.glob("*.json")):
        try:
            record = json.loads(record_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        url = str(record.get("url") or "").strip()
        item = record.get("item")
        if not url or not isinstance(item, dict):
            continue
        records[url] = {
            "url": url,
            "success": bool(record.get("success", False)),
            "failure_reason": str(record.get("failure_reason") or ""),
            "item": dict(item),
        }
    return records


def build_summary_from_staged_records(records: dict[str, dict]) -> dict[str, int]:
    total_urls = len(records)
    success_count = sum(1 for record in records.values() if bool(record.get("success")))
    return {
        "total_urls": total_urls,
        "success_count": success_count,
    }


def commit_items_file(items_path: Path, records: dict[str, dict]) -> None:
    payload_lines = [
        json.dumps(record["item"], ensure_ascii=False)
        for _, record in sorted(records.items(), key=lambda pair: pair[0])
    ]
    payload = "\n".join(payload_lines)
    if payload:
        payload += "\n"
    write_text_if_changed(items_path, payload)


async def finalize_task_from_staged_record(task: Any, staged_record: dict) -> None:
    if bool(staged_record.get("success")):
        await task.ack_task()
        return
    reason = str(staged_record.get("failure_reason") or "extraction_failed")
    await task.fail_task(reason)


def write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp_path.replace(path)


def write_summary(path: Path, summary: dict) -> None:
    write_json_idempotent(
        path,
        summary,
        identity_keys=("run_id", "list_url", "task_description"),
        volatile_keys={"created_at", "updated_at", "timestamp", "last_updated"},
    )


def try_sediment_skill(
    *,
    list_url: str,
    task_description: str,
    fields: list["FieldDefinition"],
    state: dict[str, object],
    summary: dict,
    output_dir: str,
) -> Path | None:
    try:
        from ..common.experience import SkillSedimenter

        output_path = Path(output_dir)
        collection_config: dict = {}
        cc_path = output_path / "collection_config.json"
        if cc_path.exists():
            try:
                collection_config = json.loads(cc_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        extraction_config: dict = {}
        ec_path = output_path / "extraction_config.json"
        if ec_path.exists():
            try:
                extraction_config = json.loads(ec_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        validation_failures = load_validation_failures(output_path)
        if not should_promote_skill(
            state=state,
            summary=summary,
            validation_failures=validation_failures,
        ):
            logger.info("[Pipeline] 本次运行未达到 Skill 提升条件，保留 draft skill")
            return None

        fields_dicts = [field.model_dump() for field in fields]
        plan_knowledge = ""
        for candidate in [output_path / "plan_knowledge.md", output_path.parent / "plan_knowledge.md"]:
            if candidate.exists():
                try:
                    plan_knowledge = candidate.read_text(encoding="utf-8")
                    break
                except Exception:
                    pass

        sedimenter = SkillSedimenter()
        result_path = sedimenter.sediment_from_pipeline_result(
            list_url=list_url,
            task_description=task_description,
            fields=fields_dicts,
            collection_config=collection_config,
            extraction_config=extraction_config,
            summary=summary,
            validation_failures=validation_failures,
            plan_knowledge=plan_knowledge,
            status="validated",
        )
        if result_path:
            logger.info("[Pipeline] 经验已沉淀为 Skill: %s", result_path)
        return result_path
    except Exception as exc:  # noqa: BLE001
        logger.debug("[Pipeline] 经验沉淀失败（不影响主流程）: %s", exc)
        return None


@dataclass(slots=True)
class PipelineFinalizationContext:
    list_url: str
    task_description: str
    fields: list["FieldDefinition"]
    output_dir: str
    output_path: Path
    items_path: Path
    summary_path: Path
    staging_dir: Path
    summary: dict[str, Any]
    state: dict[str, object]
    tracker: "TaskProgressTracker"
    sessions: "PipelineSessionBundle"


@dataclass(frozen=True, slots=True)
class PipelineFinalizationDependencies:
    load_staged_records: Callable[[Path], dict[str, dict]]
    build_summary_from_staged_records: Callable[[dict[str, dict]], dict[str, int]]
    load_validation_failures: Callable[[Path], list[dict]]
    classify_pipeline_result: Callable[..., dict[str, object]]
    commit_items_file: Callable[[Path, dict[str, dict]], None]
    write_summary: Callable[[Path, dict], None]
    try_sediment_skill: Callable[..., Path | None]
    cleanup_output_draft_skill: Callable[[str, str], None]


class PipelineFinalizer:
    def __init__(self, dependencies: PipelineFinalizationDependencies) -> None:
        self._deps = dependencies

    async def finalize(self, context: PipelineFinalizationContext) -> None:
        try:
            if context.state.get("error"):
                context.summary["error"] = context.state.get("error")

            committed_records = self._deps.load_staged_records(context.staging_dir)
            committed_summary = self._deps.build_summary_from_staged_records(committed_records)
            context.summary["total_urls"] = committed_summary["total_urls"]
            context.summary["success_count"] = committed_summary["success_count"]
            validation_failures = self._deps.load_validation_failures(context.output_path)
            context.summary.update(
                self._deps.classify_pipeline_result(
                    total_urls=context.summary["total_urls"],
                    success_count=context.summary["success_count"],
                    state_error=context.state.get("error"),
                    validation_failures=validation_failures,
                )
            )
            self._deps.commit_items_file(context.items_path, committed_records)
            self._deps.write_summary(context.summary_path, context.summary)

            final_status = str(context.summary.get("execution_state") or "completed")
            await context.tracker.mark_done(final_status)

            sedimented_skill_path = self._deps.try_sediment_skill(
                list_url=context.list_url,
                task_description=context.task_description,
                fields=context.fields,
                state=context.state,
                summary=context.summary,
                output_dir=context.output_dir,
            )
            if sedimented_skill_path:
                self._deps.cleanup_output_draft_skill(
                    list_url=context.list_url,
                    output_dir=context.output_dir,
                )
        finally:
            await context.sessions.stop()
