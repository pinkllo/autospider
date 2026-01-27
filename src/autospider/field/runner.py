"""Field extraction pipeline runner."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .models import FieldDefinition
from .batch_field_extractor import BatchFieldExtractor
from .batch_xpath_extractor import BatchXPathExtractor

if TYPE_CHECKING:
    from playwright.async_api import Page


async def run_field_pipeline(
    page: "Page",
    urls: list[str],
    fields: list[FieldDefinition],
    output_dir: str = "output",
    explore_count: int = 3,
    validate_count: int = 2,
    run_xpath: bool = True,
) -> dict:
    """Run field exploration and (optionally) batch XPath extraction."""
    batch_extractor = BatchFieldExtractor(
        page=page,
        fields=fields,
        explore_count=explore_count,
        validate_count=validate_count,
        output_dir=output_dir,
    )

    batch_result = await batch_extractor.run(urls=urls)
    fields_config = batch_result.to_extraction_config().get("fields", [])

    xpath_result = None
    if run_xpath and fields_config:
        xpath_extractor = BatchXPathExtractor(
            page=page,
            fields_config=fields_config,
            output_dir=output_dir,
        )
        xpath_result = await xpath_extractor.run(urls=urls)

    return {
        "batch_result": batch_result,
        "fields_config": fields_config,
        "xpath_result": xpath_result,
    }
