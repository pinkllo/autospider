"""Pydantic models and loaders for benchmark scenarios."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator

YAML_SUFFIXES = (".yaml", ".yml")
FieldMatchingStrategy = Literal["exact", "numeric_tolerance", "fuzzy", "contains"]


class ScenarioMeta(BaseModel):
    """Static scenario metadata."""

    id: str
    name: str
    description: str = ""


class TaskConfig(BaseModel):
    """Task prompt and CLI override settings."""

    request: str
    cli_overrides: dict[str, Any] = Field(default_factory=dict)


class FieldSpec(BaseModel):
    """Ground truth field contract."""

    name: str
    type: Literal["text", "number", "url", "date"] = "text"
    required: bool = True


class GroundTruthConfig(BaseModel):
    """Ground truth file location and expected field set."""

    file: str
    record_count: int
    fields: list[FieldSpec] = Field(default_factory=list)


class Thresholds(BaseModel):
    """Pass/fail thresholds for a scenario."""

    min_record_recall: float = Field(default=0.8, ge=0.0, le=1.0)
    min_field_f1: float = Field(default=0.7, ge=0.0, le=1.0)
    max_steps: int = Field(default=50, gt=0)


class EvaluationConfig(BaseModel):
    """Field matching and threshold rules."""

    match_key: str
    field_matching: dict[str, FieldMatchingStrategy] = Field(default_factory=dict)
    thresholds: Thresholds = Field(default_factory=Thresholds)

    @field_validator("field_matching")
    @classmethod
    def _require_non_empty_keys(
        cls,
        field_matching: dict[str, FieldMatchingStrategy],
    ) -> dict[str, FieldMatchingStrategy]:
        for key in field_matching:
            if not key.strip():
                raise ValueError("field_matching keys must be non-empty.")
        return field_matching


@dataclass(frozen=True)
class ResolvedTask:
    """Task config with base URL placeholders resolved."""

    request: str
    cli_overrides: dict[str, Any]


class ScenarioConfig(BaseModel):
    """Whole scenario YAML structure."""

    scenario: ScenarioMeta
    task: TaskConfig
    ground_truth: GroundTruthConfig
    evaluation: EvaluationConfig

    @classmethod
    def from_yaml(cls, path: Path) -> "ScenarioConfig":
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls.model_validate(data)

    def resolve_for_base_url(self, base_url: str) -> ResolvedTask:
        return ResolvedTask(
            request=_replace_base_url(self.task.request, base_url),
            cli_overrides=_replace_mapping_base_url(self.task.cli_overrides, base_url),
        )

    def resolve_request(self, base_url: str) -> str:
        """Compatibility entrypoint from the benchmark design doc."""
        return self.resolve_for_base_url(base_url).request


def list_scenarios(scenarios_dir: Path | None = None) -> list[str]:
    """Load and return sorted scenario ids from a directory."""
    directory = scenarios_dir or Path(__file__).resolve().parent
    configs = [ScenarioConfig.from_yaml(path) for path in _iter_yaml_files(directory)]
    return sorted(config.scenario.id for config in configs)


def load_scenario(scenario_id: str, scenarios_dir: Path | None = None) -> ScenarioConfig:
    """Load a scenario by id from a directory of YAML files."""
    directory = scenarios_dir or Path(__file__).resolve().parent
    path = directory / f"{scenario_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Scenario file not found: {path}")
    return ScenarioConfig.from_yaml(path)


def _iter_yaml_files(directory: Path) -> list[Path]:
    return [path for path in sorted(directory.iterdir()) if path.suffix in YAML_SUFFIXES]


def _replace_mapping_base_url(values: dict[str, Any], base_url: str) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    for key, value in values.items():
        resolved[key] = _replace_value_base_url(value, base_url)
    return resolved


def _replace_value_base_url(value: Any, base_url: str) -> Any:
    if isinstance(value, str):
        return _replace_base_url(value, base_url)
    if isinstance(value, dict):
        return _replace_mapping_base_url(value, base_url)
    if isinstance(value, list):
        return [_replace_value_base_url(item, base_url) for item in value]
    return value


def _replace_base_url(value: str, base_url: str) -> str:
    return value.replace("{base_url}", base_url)
