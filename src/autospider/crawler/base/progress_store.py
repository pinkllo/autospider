"""Collector progress storage boundary."""

from __future__ import annotations

from ...common.storage.persistence import CollectionProgress, ProgressPersistence


class ProgressStore:
    """Owns progress.json reads/writes for collectors."""

    def __init__(self, output_dir: str = "output") -> None:
        self._persistence = ProgressPersistence(output_dir=output_dir)

    def load(self) -> CollectionProgress | None:
        return self._persistence.load_progress()

    def save(
        self,
        *,
        status: str,
        pause_reason: str | None,
        list_url: str,
        task_description: str,
        current_page_num: int,
        collected_count: int,
        backoff_level: int,
        consecutive_success_pages: int,
    ) -> None:
        progress = CollectionProgress(
            status=(status or "RUNNING").upper(),
            pause_reason=pause_reason,
            list_url=list_url,
            task_description=task_description,
            current_page_num=current_page_num,
            collected_count=collected_count,
            backoff_level=backoff_level,
            consecutive_success_pages=consecutive_success_pages,
        )
        self._persistence.save_progress(progress)

    def has_checkpoint(self) -> bool:
        return self._persistence.has_checkpoint()

    def is_compatible(
        self,
        progress: CollectionProgress | None,
        *,
        list_url: str,
        task_description: str,
    ) -> bool:
        if progress is None:
            return False
        if progress.list_url and progress.list_url != list_url:
            return False
        if progress.task_description and progress.task_description != task_description:
            return False
        return True

    def clear(self) -> None:
        self._persistence.clear()
