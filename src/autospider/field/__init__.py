"""字段提取模块。"""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "FieldDefinition",
    "FieldExtractionResult",
    "PageExtractionRecord",
    "BatchExtractionResult",
    "CommonFieldXPath",
    "ExtractionConfig",
    "FieldRule",
    "FieldExtractor",
    "FieldDecider",
    "FieldXPathExtractor",
    "BatchFieldExtractor",
    "BatchXPathExtractor",
    "DetailPageWorker",
    "DetailPageWorkerResult",
    "extract_fields_from_urls",
    "batch_extract_fields_from_urls",
    "validate_xpath_pattern",
    "run_field_pipeline",
]

_EXPORTS = {
    "FieldDefinition": ("autospider.domain.fields", "FieldDefinition"),
    "FieldExtractionResult": ("autospider.field.models", "FieldExtractionResult"),
    "PageExtractionRecord": ("autospider.field.models", "PageExtractionRecord"),
    "BatchExtractionResult": ("autospider.field.models", "BatchExtractionResult"),
    "CommonFieldXPath": ("autospider.field.models", "CommonFieldXPath"),
    "ExtractionConfig": ("autospider.field.models", "ExtractionConfig"),
    "FieldRule": ("autospider.field.models", "FieldRule"),
    "FieldExtractor": ("autospider.field.field_extractor", "FieldExtractor"),
    "FieldDecider": ("autospider.field.field_decider", "FieldDecider"),
    "FieldXPathExtractor": ("autospider.field.xpath_pattern", "FieldXPathExtractor"),
    "BatchFieldExtractor": ("autospider.field.batch_field_extractor", "BatchFieldExtractor"),
    "BatchXPathExtractor": ("autospider.field.batch_xpath_extractor", "BatchXPathExtractor"),
    "DetailPageWorker": ("autospider.field.detail_page_worker", "DetailPageWorker"),
    "DetailPageWorkerResult": ("autospider.field.detail_page_worker", "DetailPageWorkerResult"),
    "extract_fields_from_urls": ("autospider.field.batch_field_extractor", "extract_fields_from_urls"),
    "batch_extract_fields_from_urls": (
        "autospider.field.batch_xpath_extractor",
        "batch_extract_fields_from_urls",
    ),
    "validate_xpath_pattern": ("autospider.field.xpath_pattern", "validate_xpath_pattern"),
    "run_field_pipeline": ("autospider.field.runner", "run_field_pipeline"),
}


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(f"module 'autospider.field' has no attribute {name!r}")
    module_name, attr_name = _EXPORTS[name]
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value
