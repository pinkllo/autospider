"""字段提取模块。"""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "BatchExtractionResult",
    "BatchFieldExtractor",
    "BatchXPathExtractor",
    "CommonFieldXPath",
    "DetailPageWorker",
    "DetailPageWorkerResult",
    "ExtractionConfig",
    "FieldDecider",
    "FieldDefinition",
    "FieldExtractionResult",
    "FieldExtractor",
    "FieldRule",
    "FieldXPathExtractor",
    "PageExtractionRecord",
    "batch_extract_fields_from_urls",
    "extract_fields_from_urls",
    "run_field_pipeline",
    "validate_xpath_pattern",
]

_EXPORTS = {
    "FieldDefinition": ("autospider.legacy.domain.fields", "FieldDefinition"),
    "FieldExtractionResult": ("autospider.contexts.collection.infrastructure.field.models", "FieldExtractionResult"),
    "PageExtractionRecord": ("autospider.contexts.collection.infrastructure.field.models", "PageExtractionRecord"),
    "BatchExtractionResult": ("autospider.contexts.collection.infrastructure.field.models", "BatchExtractionResult"),
    "CommonFieldXPath": ("autospider.contexts.collection.infrastructure.field.models", "CommonFieldXPath"),
    "ExtractionConfig": ("autospider.contexts.collection.infrastructure.field.models", "ExtractionConfig"),
    "FieldRule": ("autospider.contexts.collection.infrastructure.field.models", "FieldRule"),
    "FieldExtractor": ("autospider.contexts.collection.infrastructure.field.field_extractor", "FieldExtractor"),
    "FieldDecider": ("autospider.contexts.collection.infrastructure.field.field_decider", "FieldDecider"),
    "FieldXPathExtractor": ("autospider.contexts.collection.infrastructure.field.xpath_pattern", "FieldXPathExtractor"),
    "BatchFieldExtractor": ("autospider.contexts.collection.infrastructure.field.batch_field_extractor", "BatchFieldExtractor"),
    "BatchXPathExtractor": ("autospider.contexts.collection.infrastructure.field.batch_xpath_extractor", "BatchXPathExtractor"),
    "DetailPageWorker": ("autospider.contexts.collection.infrastructure.field.detail_page_worker", "DetailPageWorker"),
    "DetailPageWorkerResult": (
        "autospider.contexts.collection.infrastructure.field.detail_page_worker",
        "DetailPageWorkerResult",
    ),
    "extract_fields_from_urls": (
        "autospider.contexts.collection.infrastructure.field.batch_field_extractor",
        "extract_fields_from_urls",
    ),
    "batch_extract_fields_from_urls": (
        "autospider.contexts.collection.infrastructure.field.batch_xpath_extractor",
        "batch_extract_fields_from_urls",
    ),
    "validate_xpath_pattern": ("autospider.contexts.collection.infrastructure.field.xpath_pattern", "validate_xpath_pattern"),
    "run_field_pipeline": ("autospider.contexts.collection.infrastructure.field.runner", "run_field_pipeline"),
}


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(f"module 'autospider.field' has no attribute {name!r}")
    module_name, attr_name = _EXPORTS[name]
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value
