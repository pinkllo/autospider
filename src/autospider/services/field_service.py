"""Field extraction service."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable

from ..common.browser import create_browser_session as default_create_browser_session
from ..common.config import config
from ..field import run_field_pipeline as default_run_field_pipeline
from .service_utils import build_artifact, build_field_definitions, serialize_xpath_result


class FieldService:
    """Wraps field pipeline execution for graph capability nodes."""

    def __init__(
        self,
        *,
        create_browser_session: Callable[..., Any] = default_create_browser_session,
        run_field_pipeline: Callable[..., Awaitable[dict[str, Any]]] = default_run_field_pipeline,
        field_factory: Callable[[list[dict[str, Any]]], list[Any]] = build_field_definitions,
    ) -> None:
        self._create_browser_session = create_browser_session
        self._run_field_pipeline = run_field_pipeline
        self._field_factory = field_factory

    async def execute(self, *, params: dict[str, Any], state: dict[str, Any], thread_id: str) -> dict[str, Any]:
        use_explore = params.get("field_explore_count")
        if use_explore is None:
            use_explore = config.field_extractor.explore_count
        use_validate = params.get("field_validate_count")
        if use_validate is None:
            use_validate = config.field_extractor.validate_count

        urls = list(params.get("urls") or state.get("collected_urls") or [])
        async with self._create_browser_session(
            close_engine=True,
            headless=bool(params.get("headless", False)),
            guard_intervention_mode="interrupt",
            guard_thread_id=thread_id,
        ) as session:
            result = await self._run_field_pipeline(
                page=session.page,
                urls=urls,
                fields=self._field_factory(list(params.get("fields") or [])),
                output_dir=str(params.get("output_dir") or "output"),
                explore_count=use_explore,
                validate_count=use_validate,
                run_xpath=True,
                selected_skills=list(params.get("selected_skills") or []),
            )

        output_dir = Path(str(params.get("output_dir") or "output"))
        fields_config = list(result.get("fields_config") or [])
        xpath_result = serialize_xpath_result(result.get("xpath_result"))
        return {
            "fields_config": fields_config,
            "xpath_result": xpath_result,
            "summary": {
                "url_count": len(urls),
                "field_count": len(list(params.get("fields") or [])),
            },
            "result": {
                "field_count": len(list(params.get("fields") or [])),
                "url_count": len(urls),
                "has_xpath_result": bool(xpath_result),
                "fields_config_count": len(fields_config),
            },
            "artifacts": [
                build_artifact("field_extraction_config", output_dir / "extraction_config.json"),
                build_artifact("field_extraction_result", output_dir / "extraction_result.json"),
                build_artifact("field_extracted_items", output_dir / "extracted_items.json"),
            ],
        }
