"""Field extraction use case."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable

from ..common.browser.runtime import BrowserRuntimeSession
from ..common.config import config
from ..contracts import ExecutionRequest
from ..field import run_field_pipeline as default_run_field_pipeline
from .helpers import build_artifact, build_field_definitions, serialize_xpath_result


class ExtractFieldsUseCase:
    def __init__(
        self,
        *,
        session_cls: type = BrowserRuntimeSession,
        run_field_pipeline: Callable[..., Awaitable[dict[str, Any]]] = default_run_field_pipeline,
        field_factory: Callable[[list[dict[str, Any]]], list[Any]] = build_field_definitions,
    ) -> None:
        self._session_cls = session_cls
        self._run_field_pipeline = run_field_pipeline
        self._field_factory = field_factory

    async def execute(
        self,
        *,
        request: ExecutionRequest,
        collected_urls: list[str] | None = None,
    ) -> dict[str, Any]:
        use_explore = request.field_explore_count
        if use_explore is None:
            use_explore = config.field_extractor.explore_count
        use_validate = request.field_validate_count
        if use_validate is None:
            use_validate = config.field_extractor.validate_count

        urls = list(collected_urls or [])
        async with self._session_cls.from_request(request) as session:
            result = await self._run_field_pipeline(
                page=session.page,
                urls=urls,
                fields=self._field_factory(list(request.fields or [])),
                output_dir=request.output_dir,
                explore_count=use_explore,
                validate_count=use_validate,
                run_xpath=True,
                selected_skills=list(request.selected_skills or []),
            )

        output_dir = Path(request.output_dir)
        fields_config = list(result.get("fields_config") or [])
        xpath_result = serialize_xpath_result(result.get("xpath_result"))
        return {
            "data": {
                "fields_config": fields_config,
                "xpath_result": xpath_result,
            },
            "summary": {
                "url_count": len(urls),
                "field_count": len(list(request.fields or [])),
            },
            "artifacts": [
                build_artifact("field_extraction_config", output_dir / "extraction_config.json"),
                build_artifact("field_extraction_result", output_dir / "extraction_result.json"),
                build_artifact("field_extracted_items", output_dir / "extracted_items.json"),
            ],
        }
