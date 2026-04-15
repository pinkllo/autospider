"""Tests for benchmark scenario schema loading."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
import yaml
from pydantic import ValidationError


VALID_YAML = """
scenario:
  id: test_basic
  name: "Test Scenario"
  description: "A test scenario"
task:
  request: "采集 {base_url}/test/ 上的产品名称和价格"
  cli_overrides:
    max_pages: 3
    serial_mode: true
    headless: true
    output_dir: ".tmp/benchmark/{base_url}/test_basic"
ground_truth:
  file: "ground_truth/test_basic.jsonl"
  record_count: 5
  fields:
    - name: "product_name"
      type: "text"
      required: true
    - name: "price"
      type: "number"
      required: true
evaluation:
  match_key: "product_name"
  field_matching:
    product_name: exact
    price: numeric_tolerance
  thresholds:
    min_record_recall: 0.8
    min_field_f1: 0.7
    max_steps: 50
"""


def test_scenario_config_loads_valid_yaml() -> None:
    """Valid YAML parses into a structured config."""
    from tests.benchmark.scenarios.schema import ScenarioConfig

    tmp_path = _make_temp_dir("schema_valid")
    yaml_file = tmp_path / "test.yaml"
    yaml_file.write_text(VALID_YAML, encoding="utf-8")

    config = ScenarioConfig.from_yaml(yaml_file)

    assert config.scenario.id == "test_basic"
    assert config.ground_truth.fields[1].type == "number"
    assert config.evaluation.thresholds.max_steps == 50


def test_scenario_config_rejects_missing_id() -> None:
    """Missing scenario.id raises a validation error."""
    from tests.benchmark.scenarios.schema import ScenarioConfig

    tmp_path = _make_temp_dir("schema_missing_id")
    yaml_file = tmp_path / "bad.yaml"
    yaml_file.write_text(
        """
scenario:
  name: "No ID"
task:
  request: "test"
ground_truth:
  file: "gt.jsonl"
  record_count: 1
  fields: []
evaluation:
  match_key: "name"
  field_matching: {}
  thresholds:
    min_record_recall: 0.5
    min_field_f1: 0.5
    max_steps: 100
""",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        ScenarioConfig.from_yaml(yaml_file)


def test_resolve_request_and_cli_overrides() -> None:
    """Base URL placeholders are replaced in request and overrides."""
    from tests.benchmark.scenarios.schema import ScenarioConfig

    config = ScenarioConfig.model_validate(yaml.safe_load(VALID_YAML))

    resolved = config.resolve_for_base_url("http://localhost:9999")

    assert resolved.request == "采集 http://localhost:9999/test/ 上的产品名称和价格"
    assert resolved.cli_overrides["output_dir"] == ".tmp/benchmark/http://localhost:9999/test_basic"


def test_resolve_request_keeps_compatibility_entrypoint() -> None:
    """Design-doc entrypoint stays available for downstream callers."""
    from tests.benchmark.scenarios.schema import ScenarioConfig

    config = ScenarioConfig.model_validate(yaml.safe_load(VALID_YAML))

    assert config.resolve_request("http://localhost:7777") == "采集 http://localhost:7777/test/ 上的产品名称和价格"


def test_list_scenarios_returns_sorted_ids() -> None:
    """Scenario listing returns sorted ids from YAML files."""
    from tests.benchmark.scenarios.schema import list_scenarios

    tmp_path = _make_temp_dir("schema_list")
    a_yaml = tmp_path / "a.yaml"
    z_yaml = tmp_path / "z.yaml"
    a_yaml.write_text(VALID_YAML.replace("test_basic", "a"), encoding="utf-8")
    z_yaml.write_text(VALID_YAML.replace("test_basic", "z"), encoding="utf-8")

    assert list_scenarios(tmp_path) == ["a", "z"]


def test_list_scenarios_raises_for_invalid_yaml() -> None:
    """Broken YAML is surfaced instead of being silently ignored."""
    from tests.benchmark.scenarios.schema import list_scenarios

    tmp_path = _make_temp_dir("schema_invalid")
    bad_yaml = tmp_path / "broken.yaml"
    bad_yaml.write_text("scenario: [", encoding="utf-8")

    with pytest.raises(yaml.YAMLError):
        list_scenarios(tmp_path)


def test_scenario_config_rejects_invalid_field_matching_strategy() -> None:
    """Field matching strategies are constrained to supported values."""
    from tests.benchmark.scenarios.schema import ScenarioConfig

    bad_data = yaml.safe_load(VALID_YAML)
    bad_data["evaluation"]["field_matching"]["price"] = "approximate"

    with pytest.raises(ValidationError):
        ScenarioConfig.model_validate(bad_data)


def test_scenario_config_rejects_invalid_threshold_ranges() -> None:
    """Thresholds are range-checked instead of accepted loosely."""
    from tests.benchmark.scenarios.schema import ScenarioConfig

    bad_data = yaml.safe_load(VALID_YAML)
    bad_data["evaluation"]["thresholds"]["min_field_f1"] = 1.2
    bad_data["evaluation"]["thresholds"]["max_steps"] = 0

    with pytest.raises(ValidationError):
        ScenarioConfig.model_validate(bad_data)


def _make_temp_dir(name: str) -> Path:
    path = Path(".tmp") / "benchmark_tests" / name / uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    return path
