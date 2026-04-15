"""Tests for benchmark YAML and ground-truth data consistency."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.benchmark.scenarios.schema import load_scenario

BENCHMARK_DIR = Path(__file__).parent
SCENARIOS = {
    "categories": {"record_count": 15},
    "dynamic": {"record_count": 9},
    "variants": {"record_count": 10},
    "nested": {"record_count": 12},
}


@pytest.mark.parametrize("scenario_id", SCENARIOS)
def test_yaml_loads(scenario_id: str) -> None:
    """Scenario YAML files load through the shared schema."""
    config = load_scenario(scenario_id)

    assert config.scenario.id == scenario_id
    assert "{base_url}" in config.task.request


@pytest.mark.parametrize("scenario_id", SCENARIOS)
def test_ground_truth_count_matches_yaml(scenario_id: str) -> None:
    """Ground-truth JSONL counts match YAML record_count."""
    config = load_scenario(scenario_id)
    records = _load_ground_truth_records(config.ground_truth.file)

    assert config.ground_truth.record_count == SCENARIOS[scenario_id]["record_count"]
    assert len(records) == config.ground_truth.record_count


@pytest.mark.parametrize("scenario_id", SCENARIOS)
def test_ground_truth_match_key_unique(scenario_id: str) -> None:
    """Match keys stay unique inside each scenario ground truth."""
    config = load_scenario(scenario_id)
    records = _load_ground_truth_records(config.ground_truth.file)
    keys = [str(record[config.evaluation.match_key]).strip() for record in records]

    assert len(keys) == len(set(keys))


@pytest.mark.parametrize("scenario_id", SCENARIOS)
def test_ground_truth_has_declared_fields(scenario_id: str) -> None:
    """Each ground-truth row includes all YAML-declared fields."""
    config = load_scenario(scenario_id)
    declared_fields = {field.name for field in config.ground_truth.fields}
    records = _load_ground_truth_records(config.ground_truth.file)

    for record in records:
        assert declared_fields.issubset(record.keys())


def _load_ground_truth_records(relative_path: str) -> list[dict[str, object]]:
    ground_truth_path = BENCHMARK_DIR / relative_path
    return [
        json.loads(line)
        for line in ground_truth_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
