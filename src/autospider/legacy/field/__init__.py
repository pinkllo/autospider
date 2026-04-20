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
    "FieldExtractionResult": ("autospider.legacy.field.models", "FieldExtractionResult"),
    "PageExtractionRecord": ("autospider.legacy.field.models", "PageExtractionRecord"),
    "BatchExtractionResult": ("autospider.legacy.field.models", "BatchExtractionResult"),
    "CommonFieldXPath": ("autospider.legacy.field.models", "CommonFieldXPath"),
    "ExtractionConfig": ("autospider.legacy.field.models", "ExtractionConfig"),
    "FieldRule": ("autospider.legacy.field.models", "FieldRule"),
    "FieldExtractor": ("autospider.legacy.field.field_extractor", "FieldExtractor"),
    "FieldDecider": ("autospider.legacy.field.field_decider", "FieldDecider"),
    "FieldXPathExtractor": ("autospider.legacy.field.xpath_pattern", "FieldXPathExtractor"),
    "BatchFieldExtractor": ("autospider.legacy.field.batch_field_extractor", "BatchFieldExtractor"),
    "BatchXPathExtractor": ("autospider.legacy.field.batch_xpath_extractor", "BatchXPathExtractor"),
    "DetailPageWorker": ("autospider.legacy.field.detail_page_worker", "DetailPageWorker"),
    "DetailPageWorkerResult": (
        "autospider.legacy.field.detail_page_worker",
        "DetailPageWorkerResult",
    ),
    "extract_fields_from_urls": (
        "autospider.legacy.field.batch_field_extractor",
        "extract_fields_from_urls",
    ),
    "batch_extract_fields_from_urls": (
        "autospider.legacy.field.batch_xpath_extractor",
        "batch_extract_fields_from_urls",
    ),
    "validate_xpath_pattern": ("autospider.legacy.field.xpath_pattern", "validate_xpath_pattern"),
    "run_field_pipeline": ("autospider.legacy.field.runner", "run_field_pipeline"),
}


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(f"module 'autospider.field' has no attribute {name!r}")
    module_name, attr_name = _EXPORTS[name]
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value
