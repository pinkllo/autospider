from __future__ import annotations

from autospider.contexts.collection.domain.model import CollectionRun, PageResult


def append_page_result(run: CollectionRun, page_result: PageResult) -> CollectionRun:
    return CollectionRun(
        run_id=run.run_id,
        plan_id=run.plan_id,
        subtask_id=run.subtask_id,
        thread_id=run.thread_id,
        status=run.status,
        pages=(*run.pages, page_result),
        bindings=run.bindings,
        artifacts_dir=run.artifacts_dir,
    )
