"""Collection use cases."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable

from ..common.browser.runtime import BrowserRuntimeSession
from ..common.storage.persistence import CollectionConfig, CollectionProgress, load_collection_config
from ..contracts import ExecutionRequest
from ..crawler.batch.batch_collector import batch_collect_urls as default_batch_collect_urls
from ..crawler.explore.config_generator import generate_collection_config as default_generate_collection_config
from ..crawler.explore.url_collector import collect_detail_urls as default_collect_detail_urls
from .helpers import build_artifact, materialize_collection_config


def _build_collection_progress(*, list_url: str, task_description: str, collected_count: int) -> dict[str, Any]:
    progress = CollectionProgress(
        status="COMPLETED",
        pause_reason=None,
        list_url=list_url,
        task_description=task_description,
        current_page_num=1,
        collected_count=collected_count,
        backoff_level=0,
        consecutive_success_pages=0,
    )
    return progress.to_payload()


class CollectUrlsUseCase:
    def __init__(
        self,
        *,
        session_cls: type = BrowserRuntimeSession,
        collect_detail_urls: Callable[..., Awaitable[Any]] = default_collect_detail_urls,
    ) -> None:
        self._session_cls = session_cls
        self._collect_detail_urls = collect_detail_urls

    async def execute(self, *, request: ExecutionRequest) -> dict[str, Any]:
        params = request.model_dump(mode="python")
        async with self._session_cls.from_request(request) as session:
            result = await self._collect_detail_urls(
                page=session.page,
                list_url=request.list_url,
                task_description=request.task_description,
                explore_count=int(params.get("explore_count") or 3),
                target_url_count=request.target_url_count,
                max_pages=request.max_pages,
                output_dir=request.output_dir,
                persist_progress=False,
                selected_skills=list(request.selected_skills or []),
            )

        output_dir = Path(request.output_dir)
        collected_urls = list(result.collected_urls)
        return {
            "data": {
                "collected_urls": collected_urls,
                "collection_progress": _build_collection_progress(
                    list_url=request.list_url,
                    task_description=request.task_description,
                    collected_count=len(collected_urls),
                ),
            },
            "summary": {"collected_urls": len(collected_urls)},
            "artifacts": [
                build_artifact("collected_urls_json", output_dir / "collected_urls.json"),
                build_artifact("collected_urls_txt", output_dir / "urls.txt"),
                build_artifact("collector_spider", output_dir / "spider.py"),
            ],
        }


class GenerateCollectionConfigUseCase:
    def __init__(
        self,
        *,
        session_cls: type = BrowserRuntimeSession,
        generate_collection_config: Callable[..., Awaitable[Any]] = default_generate_collection_config,
    ) -> None:
        self._session_cls = session_cls
        self._generate_collection_config = generate_collection_config

    async def execute(self, *, request: ExecutionRequest) -> dict[str, Any]:
        params = request.model_dump(mode="python")
        async with self._session_cls.from_request(request) as session:
            config_result = await self._generate_collection_config(
                page=session.page,
                list_url=request.list_url,
                task_description=request.task_description,
                explore_count=int(params.get("explore_count") or 3),
                output_dir=request.output_dir,
                persist_progress=False,
                selected_skills=list(request.selected_skills or []),
            )

        output_dir = Path(request.output_dir)
        payload = CollectionConfig.from_dict(config_result.to_dict()).to_payload()
        return {
            "data": {"collection_config": payload},
            "summary": {
                "nav_steps": len(config_result.nav_steps),
                "has_common_detail_xpath": bool(config_result.common_detail_xpath),
                "has_pagination_xpath": bool(config_result.pagination_xpath),
                "has_jump_widget_xpath": bool(config_result.jump_widget_xpath),
            },
            "artifacts": [build_artifact("collection_config", output_dir / "collection_config.json")],
        }


class BatchCollectUrlsUseCase:
    def __init__(
        self,
        *,
        session_cls: type = BrowserRuntimeSession,
        batch_collect_urls: Callable[..., Awaitable[Any]] = default_batch_collect_urls,
    ) -> None:
        self._session_cls = session_cls
        self._batch_collect_urls = batch_collect_urls

    async def execute(
        self,
        *,
        request: ExecutionRequest,
        collection_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        config_payload = dict(collection_config or {})
        params = request.model_dump(mode="python")
        config_path = str(params.get("config_path") or "").strip()
        if not config_path and config_payload:
            config_path = str(materialize_collection_config(request.output_dir, config_payload))
        if not config_path:
            raise ValueError("missing_collection_config")

        async with self._session_cls.from_request(request) as session:
            result = await self._batch_collect_urls(
                page=session.page,
                config_path=config_path,
                target_url_count=request.target_url_count,
                max_pages=request.max_pages,
                output_dir=request.output_dir,
                persist_progress=False,
            )

        output_dir = Path(request.output_dir)
        if not config_payload:
            loaded_config = load_collection_config(config_path, strict=True)
            if loaded_config is None:
                raise ValueError("missing_collection_config")
            config_payload = loaded_config.to_payload()
        collected_urls = list(result.collected_urls)
        return {
            "data": {
                "collection_config": config_payload,
                "collected_urls": collected_urls,
                "collection_progress": _build_collection_progress(
                    list_url=str(config_payload.get("list_url") or request.list_url or ""),
                    task_description=str(config_payload.get("task_description") or request.task_description or ""),
                    collected_count=len(collected_urls),
                ),
            },
            "summary": {"collected_urls": len(collected_urls)},
            "artifacts": [
                build_artifact("batch_collected_urls_json", output_dir / "collected_urls.json"),
                build_artifact("batch_collected_urls_txt", output_dir / "urls.txt"),
            ],
        }
