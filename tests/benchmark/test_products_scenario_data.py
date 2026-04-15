"""Tests for benchmark products scenario data assets."""

from __future__ import annotations

import json
from pathlib import Path

from tests.benchmark.scenarios.schema import load_scenario

BENCHMARK_DIR = Path(__file__).parent
GROUND_TRUTH_PATH = BENCHMARK_DIR / "ground_truth" / "products.jsonl"
REQUIRED_FIELDS = {"product_name", "price", "brand", "specs"}


def test_products_yaml_loads() -> None:
    """Products scenario YAML loads through the shared schema."""
    config = load_scenario("products")

    assert config.scenario.id == "products"
    assert "{base_url}" in config.task.request
    assert config.ground_truth.record_count == 15
    assert config.evaluation.match_key == "product_name"


def test_products_ground_truth_has_expected_record_count() -> None:
    """Products ground truth contains exactly 15 JSONL records."""
    records = _load_ground_truth_records()

    assert len(records) == 15


def test_products_ground_truth_match_key_is_unique() -> None:
    """Products match_key stays unique across all rows."""
    records = _load_ground_truth_records()
    keys = [record["product_name"] for record in records]

    assert len(keys) == len(set(keys))


def test_products_ground_truth_fields_match_design() -> None:
    """Products rows expose the core fields used by the pages and spec."""
    records = _load_ground_truth_records()

    for record in records:
        assert REQUIRED_FIELDS.issubset(record.keys())


def _load_ground_truth_records() -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in GROUND_TRUTH_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
