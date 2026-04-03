"""Collection services for graph capability nodes."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable

from ..common.browser import create_browser_session as default_create_browser_session
from ..crawler.batch.batch_collector import batch_collect_urls as default_batch_collect_urls
from ..crawler.explore.config_generator import generate_collection_config as default_generate_collection_config
from ..crawler.explore.url_collector import collect_detail_urls as default_collect_detail_urls
from .service_utils import (
    build_artifact,
    collection_config_payload,
    collection_progress_payload,
    load_collection_config_payload,
    materialize_collection_config,
)


class CollectionService:
    """Wraps collection/config-generation workflows with normalized outputs."""

    def __init__(
        self,
        *,
        create_browser_session: Callable[..., Any] = default_create_browser_session,
        collect_detail_urls: Callable[..., Awaitable[Any]] = default_collect_detail_urls,
        generate_collection_config: Callable[..., Awaitable[Any]] = default_generate_collection_config,
        batch_collect_urls: Callable[..., Awaitable[Any]] = default_batch_collect_urls,
    ) -> None:
        self._create_browser_session = create_browser_session
        self._collect_detail_urls = collect_detail_urls
        self._generate_collection_config = generate_collection_config
        self._batch_collect_urls = batch_collect_urls

    @staticmethod
    def _session_options(*, params: dict[str, Any], thread_id: str) -> dict[str, Any]:
        return {
            "close_engine": True,
            "headless": bool(params.get("headless", False)),
            "guard_intervention_mode": "interrupt",
            "guard_thread_id": thread_id,
        }

    async def collect_urls(self, *, params: dict[str, Any], thread_id: str) -> dict[str, Any]:
        async with self._create_browser_session(**self._session_options(params=params, thread_id=thread_id)) as session:
            result = await self._collect_detail_urls(
                page=session.page,
                list_url=str(params.get("list_url") or ""),
                task_description=str(params.get("task") or ""),
                explore_count=int(params.get("explore_count") or 3),
                target_url_count=params.get("target_url_count"),
                max_pages=params.get("max_pages"),
                output_dir=str(params.get("output_dir") or "output"),
                persist_progress=False,
                selected_skills=list(params.get("selected_skills") or []),
            )

        output_dir = Path(str(params.get("output_dir") or "output"))
        collected_urls = list(result.collected_urls)
        return {
            "collected_urls": collected_urls,
            "collection_progress": collection_progress_payload(
                list_url=str(params.get("list_url") or ""),
                task_description=str(params.get("task") or ""),
                collected_count=len(collected_urls),
            ),
            "summary": {"collected_urls": len(collected_urls)},
            "result": {"collected_urls": len(collected_urls)},
            "artifacts": [
                build_artifact("collected_urls_json", output_dir / "collected_urls.json"),
                build_artifact("collected_urls_txt", output_dir / "urls.txt"),
                build_artifact("collector_spider", output_dir / "spider.py"),
            ],
        }

    async def generate_config(self, *, params: dict[str, Any], thread_id: str) -> dict[str, Any]:
        async with self._create_browser_session(**self._session_options(params=params, thread_id=thread_id)) as session:
            config_result = await self._generate_collection_config(
                page=session.page,
                list_url=str(params.get("list_url") or ""),
                task_description=str(params.get("task") or ""),
                explore_count=int(params.get("explore_count") or 3),
                output_dir=str(params.get("output_dir") or "output"),
                persist_progress=False,
                selected_skills=list(params.get("selected_skills") or []),
            )

        output_dir = Path(str(params.get("output_dir") or "output"))
        payload = collection_config_payload(config_result)
        return {
            "collection_config": payload,
            "summary": {
                "nav_steps": len(config_result.nav_steps),
                "has_common_detail_xpath": bool(config_result.common_detail_xpath),
                "has_pagination_xpath": bool(config_result.pagination_xpath),
                "has_jump_widget_xpath": bool(config_result.jump_widget_xpath),
            },
            "result": {
                "nav_steps": len(config_result.nav_steps),
                "has_common_detail_xpath": bool(config_result.common_detail_xpath),
                "has_pagination_xpath": bool(config_result.pagination_xpath),
                "has_jump_widget_xpath": bool(config_result.jump_widget_xpath),
            },
            "artifacts": [build_artifact("collection_config", output_dir / "collection_config.json")],
        }

    async def batch_collect(self, *, params: dict[str, Any], state: dict[str, Any], thread_id: str) -> dict[str, Any]:
        collection_config = dict(state.get("collection_config") or {})
        config_path = str(params.get("config_path") or "").strip()
        if not config_path and collection_config:
            config_path = str(
                materialize_collection_config(
                    str(params.get("output_dir") or "output"),
                    collection_config,
                )
            )
        if not config_path:
            raise ValueError("missing_collection_config")

        async with self._create_browser_session(**self._session_options(params=params, thread_id=thread_id)) as session:
            result = await self._batch_collect_urls(
                page=session.page,
                config_path=config_path,
                target_url_count=params.get("target_url_count"),
                max_pages=params.get("max_pages"),
                output_dir=str(params.get("output_dir") or "output"),
                persist_progress=False,
            )

        output_dir = Path(str(params.get("output_dir") or "output"))
        if not collection_config:
            collection_config = load_collection_config_payload(config_path)
        collected_urls = list(result.collected_urls)
        return {
            "collection_config": collection_config,
            "collected_urls": collected_urls,
            "collection_progress": collection_progress_payload(
                list_url=str(collection_config.get("list_url") or params.get("list_url") or ""),
                task_description=str(
                    collection_config.get("task_description") or params.get("task") or ""
                ),
                collected_count=len(collected_urls),
            ),
            "summary": {"collected_urls": len(collected_urls)},
            "result": {"collected_urls": len(collected_urls)},
            "artifacts": [
                build_artifact("batch_collected_urls_json", output_dir / "collected_urls.json"),
                build_artifact("batch_collected_urls_txt", output_dir / "urls.txt"),
            ],
        }
