from __future__ import annotations

from autospider.domain.planning import SubTask
from autospider.field.batch_xpath_extractor import BatchXPathExtractor
from autospider.pipeline.runner import _prepare_fields_config
from autospider.pipeline.worker import SubTaskWorker


class _DummyPage:
    pass


def test_subtask_worker_uses_explicit_context_for_category_field():
    subtask = SubTask(
        id="category_01",
        name="水利工程采集",
        list_url="https://example.com/list",
        task_description="采集该分类数据，筛选条件为'水利工程'子类",
        context={"category_name": "水利工程"},
    )
    raw_fields = [
        {"name": "project_name", "description": "项目名称", "required": True, "data_type": "text"},
        {"name": "category", "description": "项目所属分类", "required": True, "data_type": "text"},
    ]
    worker = SubTaskWorker(subtask=subtask, fields=raw_fields, output_dir="output", headless=True)

    prepared = worker._prepare_fields()
    category = next((f for f in prepared if f.name == "category"), None)
    project_name = next((f for f in prepared if f.name == "project_name"), None)

    assert category is not None
    assert category.extraction_source == "subtask_context"
    assert category.fixed_value == "水利工程"
    assert project_name is not None
    assert project_name.extraction_source is None


def test_subtask_worker_prefers_explicit_context_over_name_guess():
    subtask = SubTask(
        id="category_02",
        name="默认名称",
        list_url="https://example.com/list",
        task_description="采集该分类数据",
        context={"category_name": "工程建设"},
    )
    raw_fields = [
        {"name": "category", "description": "项目所属分类", "required": True, "data_type": "text"},
    ]
    worker = SubTaskWorker(subtask=subtask, fields=raw_fields, output_dir="output", headless=True)

    prepared = worker._prepare_fields()
    category = prepared[0]

    assert category.extraction_source == "subtask_context"
    assert category.fixed_value == "工程建设"


def test_subtask_worker_does_not_guess_context_without_explicit_value():
    subtask = SubTask(
        id="category_03",
        name="土地矿业采集",
        list_url="https://example.com/list",
        task_description="访问'工程建设'与'土地矿业'分类后采集数据",
    )
    raw_fields = [
        {"name": "category_name", "description": "项目所属分类", "required": True, "data_type": "text"},
    ]
    worker = SubTaskWorker(subtask=subtask, fields=raw_fields, output_dir="output", headless=True)

    prepared = worker._prepare_fields()
    category = prepared[0]

    assert category.extraction_source is None
    assert category.fixed_value is None


def test_prepare_fields_config_accepts_required_context_field_without_xpath():
    fields_config = [
        {
            "name": "category",
            "description": "项目所属分类",
            "xpath": None,
            "required": True,
            "data_type": "text",
            "extraction_source": "subtask_context",
            "fixed_value": "交通运输工程",
        }
    ]
    valid_fields, missing_required, missing_optional = _prepare_fields_config(fields_config)

    assert len(valid_fields) == 1
    assert valid_fields[0]["extraction_source"] == "subtask_context"
    assert valid_fields[0]["fixed_value"] == "交通运输工程"
    assert missing_required == []
    assert missing_optional == []


def test_batch_xpath_extractor_resolve_non_xpath_field_value_for_context():
    extractor = BatchXPathExtractor(
        page=_DummyPage(),
        fields_config=[],
    )

    value, method = extractor._resolve_non_xpath_field_value(
        {"name": "category", "extraction_source": "subtask_context", "fixed_value": "佛教部"},
        url="https://example.com/detail",
    )
    assert value == "佛教部"
    assert method == "subtask_context"
