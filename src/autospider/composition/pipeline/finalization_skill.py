"""Draft-skill cleanup and promotion helpers."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Callable
from urllib.parse import urlparse

import yaml

from autospider.contexts.experience.application.handlers import (
    CollectionFinalizedHandler,
    CollectionFinalizedPayload,
)
from autospider.contexts.experience.application.skill_promotion import SkillSedimenter
from autospider.contexts.experience.infrastructure.repositories.skill_repository import (
    SkillRepository as ExperienceSkillRepository,
)
from autospider.platform.observability.logger import get_logger

if TYPE_CHECKING:
    from .finalization import PipelineFinalizationContext

logger = get_logger(__name__)


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


def promote_pipeline_skill(
    context: "PipelineFinalizationContext",
    *,
    should_promote_skill_fn: Callable[..., bool],
    cleanup_output_draft_skill_fn: Callable[[str, str], None],
) -> Path | None:
    if not should_promote_skill_fn(
        state_error=context.runtime_state.error,
        summary=context.summary,
        validation_failures=context.runtime_state.validation_failures,
    ):
        logger.info(
            "[Pipeline] 跳过 Skill 晋升: promotion_state=%s, success=%s/%s",
            str(context.summary.get("promotion_state") or ""),
            int(context.summary.get("success_count", 0) or 0),
            int(context.summary.get("total_urls", 0) or 0),
        )
        return None

    promoted_path = CollectionFinalizedHandler(SkillSedimenter(ExperienceSkillRepository())).handle(
        CollectionFinalizedPayload(
            run_id=str(context.summary.get("execution_id") or context.summary.get("run_id") or ""),
            plan_id=str(context.task_plan.get("plan_id") or ""),
            status=str(
                context.summary.get("outcome_state") or context.summary.get("execution_state") or ""
            ),
            artifacts_dir=context.output_dir,
        )
    )
    if promoted_path is None:
        logger.warning(
            "[Pipeline] Skill 晋升未生成有效结果: list_url=%s, task=%s",
            context.list_url,
            context.task_description[:120],
        )
        return None

    cleanup_output_draft_skill_fn(context.list_url, context.output_dir)
    logger.info("[Pipeline] Skill 已晋升到正式目录: %s", promoted_path)
    return promoted_path
