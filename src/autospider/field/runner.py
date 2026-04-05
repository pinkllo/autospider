"""字段提取单链路运行器：LLM 样本采集 -> 规则生成 -> 规则验证 -> 规则执行。"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

from ..common.config import config
from ..common.experience import SkillRuntime
from ..common.storage.idempotent_io import write_json_idempotent
from ..domain.fields import FieldDefinition
from .batch_xpath_extractor import BatchXPathExtractor
from .field_extractor import FieldExtractor
from .models import CommonFieldXPath, PageExtractionRecord
from .xpath_helpers import normalize_xpath_majority_key
from .xpath_pattern import FieldXPathExtractor

if TYPE_CHECKING:
    from playwright.async_api import Page


def _normalize_value(value: str | None) -> str:
    return " ".join(str(value or "").strip().split()).lower()


def _record_to_dict(record: PageExtractionRecord) -> dict:
    return {
        "url": record.url,
        "success": record.success,
        "fields": [
            {
                "field_name": field.field_name,
                "value": field.value,
                "xpath": field.xpath,
                "confidence": field.confidence,
                "error": field.error,
                "xpath_candidates": field.xpath_candidates,
            }
            for field in record.fields
        ],
    }


def _items_from_records(records: list[PageExtractionRecord]) -> list[dict]:
    items: list[dict] = []
    for record in records:
        item = {"url": record.url}
        for field in record.fields:
            item[field.field_name] = field.value
        items.append(item)
    return items


def _required_field_names(fields: list[FieldDefinition]) -> set[str]:
    return {field.name for field in fields if field.required}


def _is_valid_sample(record: PageExtractionRecord, fields: list[FieldDefinition]) -> bool:
    required_names = _required_field_names(fields)
    if not required_names:
        return True

    for field in record.fields:
        if field.field_name not in required_names:
            continue
        if field.value is None:
            return False
        if not (field.xpath or "").strip():
            return False

    return all(record.get_field_value(name) is not None for name in required_names)


def _build_template_signature(record: PageExtractionRecord, fields: list[FieldDefinition]) -> str:
    parts: list[str] = []
    for field in fields:
        if not field.required:
            continue
        field_result = record.get_field(field.name)
        xpath = (field_result.xpath if field_result else "") or ""
        normalized = normalize_xpath_majority_key(xpath)
        if not normalized:
            return ""
        parts.append(f"{field.name}:{normalized}")
    return "|".join(parts)


def _build_fields_config(
    fields: list[FieldDefinition],
    common_xpaths: list[CommonFieldXPath],
) -> list[dict]:
    xpath_map = {xpath.field_name: xpath for xpath in common_xpaths}
    return [
        {
            "name": field.name,
            "description": field.description,
            "xpath": xpath_map[field.name].xpath_pattern if field.name in xpath_map else None,
            "xpath_fallbacks": xpath_map[field.name].fallback_xpaths if field.name in xpath_map else [],
            "xpath_validated": field.name in xpath_map,
            "required": field.required,
            "data_type": field.data_type,
            "extraction_source": field.extraction_source,
            "fixed_value": field.fixed_value,
        }
        for field in fields
    ]


def _required_rules_ready(fields_config: list[dict]) -> bool:
    for field in fields_config:
        if not bool(field.get("required", True)):
            continue
        if field.get("xpath"):
            continue
        source = str(field.get("extraction_source") or "").strip().lower()
        if source in {"constant", "subtask_context", "task_url"}:
            continue
        if str(field.get("data_type") or "").strip().lower() == "url":
            continue
        return False
    return True


def _records_match(
    llm_record: PageExtractionRecord,
    rule_record: PageExtractionRecord,
    fields: list[FieldDefinition],
) -> tuple[bool, list[dict]]:
    errors: list[dict] = []

    if not rule_record.success:
        for field in rule_record.fields:
            if field.error:
                errors.append(
                    {
                        "field_name": field.field_name,
                        "llm_value": llm_record.get_field_value(field.field_name),
                        "rule_value": field.value,
                        "error": field.error,
                    }
                )

    for field in fields:
        if not field.required:
            continue
        llm_value = _normalize_value(llm_record.get_field_value(field.name))
        rule_value = _normalize_value(rule_record.get_field_value(field.name))
        if llm_value != rule_value:
            errors.append(
                {
                    "field_name": field.name,
                    "llm_value": llm_record.get_field_value(field.name),
                    "rule_value": rule_record.get_field_value(field.name),
                    "error": "value_mismatch",
                }
            )

    return len(errors) == 0, errors


def _save_outputs(
    *,
    output_dir: str,
    fields: list[FieldDefinition],
    fields_config: list[dict],
    sample_records: list[PageExtractionRecord],
    validation_records: list[PageExtractionRecord],
    final_records: list[PageExtractionRecord],
    validation_failures: list[dict],
) -> None:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    write_json_idempotent(
        output_path / "extraction_config.json",
        {"fields": fields_config, "created_at": ""},
        volatile_keys=set(),
    )

    detail_payload = {
        "fields": [field.model_dump(mode="python") for field in fields],
        "common_fields": fields_config,
        "sample_records": [_record_to_dict(record) for record in sample_records],
        "validation_records": [_record_to_dict(record) for record in validation_records],
        "records": [_record_to_dict(record) for record in final_records],
        "validation_failures": validation_failures,
        "validation_success": not validation_failures and bool(fields_config),
        "total_urls_explored": len(sample_records),
        "total_urls_validated": len(validation_records),
        "created_at": "",
    }
    write_json_idempotent(output_path / "extraction_result.json", detail_payload)
    write_json_idempotent(
        output_path / "extracted_items.json",
        _items_from_records(final_records),
        volatile_keys=set(),
    )


async def run_field_pipeline(
    page: "Page",
    urls: list[str],
    fields: list[FieldDefinition],
    output_dir: str = "output",
    explore_count: int | None = None,
    validate_count: int | None = None,
    run_xpath: bool = True,
    selected_skills: list[dict[str, str]] | None = None,
) -> dict:
    explore_count = explore_count or config.field_extractor.explore_count
    validate_count = validate_count or config.field_extractor.validate_count
    skill_runtime = SkillRuntime()

    unique_urls: list[str] = []
    seen: set[str] = set()
    for raw_url in urls:
        url = str(raw_url or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        unique_urls.append(url)

    if not unique_urls:
        _save_outputs(
            output_dir=output_dir,
            fields=fields,
            fields_config=[],
            sample_records=[],
            validation_records=[],
            final_records=[],
            validation_failures=[],
        )
        return {
            "records": [],
            "fields_config": [],
            "xpath_result": {"fields": [], "records": [], "total_urls": 0, "success_count": 0},
            "validation_failures": [],
        }

    llm_extractor = FieldExtractor(
        page=page,
        fields=fields,
        output_dir=output_dir,
        max_nav_steps=config.field_extractor.max_nav_steps,
        skill_runtime=skill_runtime,
    )
    if selected_skills:
        llm_extractor.selected_skills = list(selected_skills)

    xpath_extractor = FieldXPathExtractor()
    processed_records: dict[str, PageExtractionRecord] = {}
    sample_groups: dict[str, list[PageExtractionRecord]] = defaultdict(list)
    sample_records: list[PageExtractionRecord] = []
    validation_records: list[PageExtractionRecord] = []
    validation_failures: list[dict] = []
    fields_config: list[dict] = []
    validated = False
    cursor = 0

    while cursor < len(unique_urls) and not validated:
        url = unique_urls[cursor]
        cursor += 1
        record = await llm_extractor.extract_from_url(url)
        processed_records[url] = record

        if not _is_valid_sample(record, fields):
            continue

        signature = _build_template_signature(record, fields)
        if not signature:
            continue

        sample_groups[signature].append(record)
        if len(sample_groups[signature]) < explore_count:
            continue

        candidate_samples = list(sample_groups[signature][:explore_count])
        common_xpaths = await xpath_extractor.extract_all_common_patterns(
            records=candidate_samples,
            field_names=[field.name for field in fields],
        )
        candidate_fields_config = _build_fields_config(fields, common_xpaths)
        if not _required_rules_ready(candidate_fields_config):
            continue

        candidate_rule_extractor = BatchXPathExtractor(
            page=page,
            fields_config=candidate_fields_config,
            output_dir=output_dir,
            skill_runtime=skill_runtime,
        )

        current_validation_records: list[PageExtractionRecord] = []
        current_validation_failures: list[dict] = []
        validation_ok = True

        for _ in range(validate_count):
            if cursor >= len(unique_urls):
                validation_ok = False
                break

            validation_url = unique_urls[cursor]
            cursor += 1

            llm_record = await llm_extractor.extract_from_url(validation_url)
            processed_records[validation_url] = llm_record
            current_validation_records.append(llm_record)

            if _is_valid_sample(llm_record, fields):
                validation_signature = _build_template_signature(llm_record, fields)
                if validation_signature == signature:
                    sample_groups[signature].append(llm_record)

            rule_record = await candidate_rule_extractor._extract_from_url(validation_url)
            matched, errors = _records_match(llm_record, rule_record, fields)
            if not matched:
                validation_ok = False
                current_validation_failures.append(
                    {
                        "url": validation_url,
                        "fields": errors,
                    }
                )

        sample_records = candidate_samples
        validation_records = current_validation_records

        if validation_ok and len(current_validation_records) == validate_count:
            fields_config = candidate_fields_config
            validated = True
            break

        validation_failures.extend(current_validation_failures)

    final_records: list[PageExtractionRecord] = []

    if run_xpath and validated and fields_config:
        rule_extractor = BatchXPathExtractor(
            page=page,
            fields_config=fields_config,
            output_dir=output_dir,
            skill_runtime=skill_runtime,
        )

        remaining_urls = [url for url in unique_urls if url not in processed_records]
        for url in remaining_urls:
            processed_records[url] = await rule_extractor._extract_from_url(url)
    else:
        while cursor < len(unique_urls):
            url = unique_urls[cursor]
            cursor += 1
            if url in processed_records:
                continue
            processed_records[url] = await llm_extractor.extract_from_url(url)

    for url in unique_urls:
        record = processed_records.get(url)
        if record is not None:
            final_records.append(record)

    success_count = sum(1 for record in final_records if record.success)
    xpath_result = {
        "fields": fields_config,
        "records": [_record_to_dict(record) for record in final_records],
        "total_urls": len(final_records),
        "success_count": success_count,
    }

    _save_outputs(
        output_dir=output_dir,
        fields=fields,
        fields_config=fields_config,
        sample_records=sample_records,
        validation_records=validation_records,
        final_records=final_records,
        validation_failures=validation_failures,
    )

    return {
        "records": final_records,
        "fields_config": fields_config,
        "xpath_result": xpath_result,
        "validation_failures": validation_failures,
    }
