# Benchmark 闭环评测系统实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个端到端闭环评测系统，包括模拟网站、测试题集、评估引擎、报告系统和双入口（CLI + pytest）。

**Architecture:** 模拟网站使用静态 HTML + JS 提供确定性测试环境，pytest fixture 启动本地静态文件服务器。场景用 YAML 定义任务输入和评估规则，ground truth 用 JSONL 存储。评估引擎对比采集结果与 ground truth 计算指标，报告系统生成 JSON + Markdown 格式输出。

**Tech Stack:** Python 3.10+, pytest, Pydantic, PyYAML, HTML/CSS/JS (静态), http.server (标准库)

**Spec:** `docs/superpowers/specs/2026-04-14-benchmark-design.md`

---

## File Structure

### 新建文件

| 文件路径 | 职责 |
|----------|------|
| `tests/benchmark/__init__.py` | 包初始化 |
| `tests/benchmark/scenarios/__init__.py` | 场景包初始化 |
| `tests/benchmark/scenarios/schema.py` | 场景 YAML 的 Pydantic 模型，加载/校验逻辑 |
| `tests/benchmark/scenarios/products.yaml` | 场景 1 定义 |
| `tests/benchmark/scenarios/categories.yaml` | 场景 2 定义 |
| `tests/benchmark/scenarios/dynamic.yaml` | 场景 3 定义 |
| `tests/benchmark/scenarios/variants.yaml` | 场景 4 定义 |
| `tests/benchmark/scenarios/nested.yaml` | 场景 5 定义 |
| `tests/benchmark/ground_truth/products.jsonl` | 场景 1 标准答案 |
| `tests/benchmark/ground_truth/categories.jsonl` | 场景 2 标准答案 |
| `tests/benchmark/ground_truth/dynamic.jsonl` | 场景 3 标准答案 |
| `tests/benchmark/ground_truth/variants.jsonl` | 场景 4 标准答案 |
| `tests/benchmark/ground_truth/nested.jsonl` | 场景 5 标准答案 |
| `tests/benchmark/mock_site/server.py` | 静态文件服务器 |
| `tests/benchmark/mock_site/shared/style.css` | 全站共享样式 |
| `tests/benchmark/mock_site/shared/pagination.js` | 翻页 JS |
| `tests/benchmark/mock_site/shared/dynamic_load.js` | 动态加载 JS |
| `tests/benchmark/mock_site/shared/tabs.js` | Tab 切换 JS |
| `tests/benchmark/mock_site/scenarios/products/` | 场景1 页面文件 |
| `tests/benchmark/mock_site/scenarios/categories/` | 场景2 页面文件 |
| `tests/benchmark/mock_site/scenarios/dynamic/` | 场景3 页面文件 |
| `tests/benchmark/mock_site/scenarios/variants/` | 场景4 页面文件 |
| `tests/benchmark/mock_site/scenarios/nested/` | 场景5 页面文件 |
| `tests/benchmark/metrics.py` | 指标计算（P/R/F1/步骤数） |
| `tests/benchmark/evaluator.py` | 评估引擎（结果对比） |
| `tests/benchmark/reporter.py` | 报告生成器（JSON + Markdown） |
| `tests/benchmark/runner.py` | 基准测试运行器核心 |
| `tests/benchmark/conftest.py` | pytest fixtures |
| `tests/benchmark/test_benchmark.py` | pytest 测试入口 |

### 修改文件

| 文件路径 | 变更 |
|----------|------|
| `src/autospider/cli.py` | 新增 `benchmark` 命令 |
| `.gitignore` | 添加 `tests/benchmark/reports/` |

---

## Task 1: 场景定义模型与加载器

**Files:**
- Create: `tests/benchmark/__init__.py`
- Create: `tests/benchmark/scenarios/__init__.py`
- Create: `tests/benchmark/scenarios/schema.py`
- Test: `tests/benchmark/test_scenario_schema.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/benchmark/test_scenario_schema.py
"""Test scenario YAML schema loading and validation."""
import pytest
from pathlib import Path


def test_scenario_config_loads_valid_yaml(tmp_path: Path):
    """Valid YAML should parse into ScenarioConfig."""
    from tests.benchmark.scenarios.schema import ScenarioConfig

    yaml_content = """
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
    output_dir: ".tmp/benchmark/test_basic"

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
    yaml_file = tmp_path / "test.yaml"
    yaml_file.write_text(yaml_content, encoding="utf-8")

    config = ScenarioConfig.from_yaml(yaml_file)
    assert config.scenario.id == "test_basic"
    assert config.scenario.name == "Test Scenario"
    assert config.task.request == "采集 {base_url}/test/ 上的产品名称和价格"
    assert config.task.cli_overrides["serial_mode"] is True
    assert config.ground_truth.record_count == 5
    assert len(config.ground_truth.fields) == 2
    assert config.evaluation.match_key == "product_name"
    assert config.evaluation.field_matching["price"] == "numeric_tolerance"
    assert config.evaluation.thresholds.min_record_recall == 0.8


def test_scenario_config_rejects_missing_id(tmp_path: Path):
    """Missing scenario.id should raise ValidationError."""
    from tests.benchmark.scenarios.schema import ScenarioConfig
    from pydantic import ValidationError

    yaml_content = """
scenario:
  name: "No ID"
  description: "Missing id"
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
"""
    yaml_file = tmp_path / "bad.yaml"
    yaml_file.write_text(yaml_content, encoding="utf-8")

    with pytest.raises(ValidationError):
        ScenarioConfig.from_yaml(yaml_file)


def test_resolve_request_url():
    """base_url placeholder should be replaced."""
    from tests.benchmark.scenarios.schema import ScenarioConfig

    config = ScenarioConfig.model_validate({
        "scenario": {"id": "t", "name": "t", "description": "t"},
        "task": {"request": "采集 {base_url}/products/"},
        "ground_truth": {"file": "gt.jsonl", "record_count": 1, "fields": []},
        "evaluation": {
            "match_key": "name",
            "field_matching": {},
            "thresholds": {"min_record_recall": 0.5, "min_field_f1": 0.5, "max_steps": 99},
        },
    })
    resolved = config.resolve_request("http://localhost:8888")
    assert resolved == "采集 http://localhost:8888/products/"


def test_list_available_scenarios():
    """list_scenarios should return scenario ids from yaml files."""
    from tests.benchmark.scenarios.schema import list_scenarios

    scenarios = list_scenarios()
    assert isinstance(scenarios, list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/benchmark/test_scenario_schema.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tests.benchmark'`

- [ ] **Step 3: Write minimal implementation**

```python
# tests/benchmark/__init__.py
"""AutoSpider Benchmark — 闭环评测系统."""
```

```python
# tests/benchmark/scenarios/__init__.py
"""Benchmark scenario definitions."""
```

```python
# tests/benchmark/scenarios/schema.py
"""Pydantic models for benchmark scenario YAML configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field


class ScenarioMeta(BaseModel):
    id: str
    name: str
    description: str = ""


class TaskConfig(BaseModel):
    request: str
    cli_overrides: dict[str, Any] = Field(default_factory=dict)


class FieldSpec(BaseModel):
    name: str
    type: Literal["text", "number", "url", "date"] = "text"
    required: bool = True


class GroundTruthConfig(BaseModel):
    file: str
    record_count: int
    fields: list[FieldSpec] = Field(default_factory=list)


class Thresholds(BaseModel):
    min_record_recall: float = 0.8
    min_field_f1: float = 0.7
    max_steps: int = 50


class EvaluationConfig(BaseModel):
    match_key: str
    field_matching: dict[str, str] = Field(default_factory=dict)
    thresholds: Thresholds = Field(default_factory=Thresholds)


class ScenarioConfig(BaseModel):
    scenario: ScenarioMeta
    task: TaskConfig
    ground_truth: GroundTruthConfig
    evaluation: EvaluationConfig

    @classmethod
    def from_yaml(cls, path: Path) -> "ScenarioConfig":
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls.model_validate(data)

    def resolve_request(self, base_url: str) -> str:
        return self.task.request.replace("{base_url}", base_url)


_SCENARIOS_DIR = Path(__file__).parent


def list_scenarios() -> list[str]:
    ids = []
    for yaml_file in sorted(_SCENARIOS_DIR.glob("*.yaml")):
        try:
            config = ScenarioConfig.from_yaml(yaml_file)
            ids.append(config.scenario.id)
        except Exception:
            continue
    return ids


def load_scenario(scenario_id: str) -> ScenarioConfig:
    yaml_path = _SCENARIOS_DIR / f"{scenario_id}.yaml"
    if not yaml_path.exists():
        raise FileNotFoundError(f"场景文件不存在: {yaml_path}")
    return ScenarioConfig.from_yaml(yaml_path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/benchmark/test_scenario_schema.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tests/benchmark/__init__.py tests/benchmark/scenarios/ tests/benchmark/test_scenario_schema.py
git commit -m "feat(benchmark): add scenario YAML schema and loader"
```

---

## Task 2: 模拟网站静态文件服务器

**Files:**
- Create: `tests/benchmark/mock_site/__init__.py`
- Create: `tests/benchmark/mock_site/server.py`
- Test: `tests/benchmark/test_mock_server.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/benchmark/test_mock_server.py
"""Test mock site static file server."""
import urllib.request
from pathlib import Path

import pytest


@pytest.fixture()
def sample_site(tmp_path: Path):
    index = tmp_path / "index.html"
    index.write_text("<html><body>Hello</body></html>", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "page.html").write_text("<html><body>Sub</body></html>", encoding="utf-8")
    return tmp_path


def test_server_starts_and_serves_files(sample_site: Path):
    from tests.benchmark.mock_site.server import MockSiteServer

    server = MockSiteServer(root_dir=sample_site, port=0)
    server.start()
    try:
        base = f"http://localhost:{server.port}"
        resp = urllib.request.urlopen(f"{base}/index.html")
        assert resp.status == 200
        body = resp.read().decode()
        assert "Hello" in body

        resp2 = urllib.request.urlopen(f"{base}/sub/page.html")
        assert resp2.status == 200
        assert "Sub" in resp2.read().decode()
    finally:
        server.stop()


def test_server_returns_404_for_missing(sample_site: Path):
    from tests.benchmark.mock_site.server import MockSiteServer

    server = MockSiteServer(root_dir=sample_site, port=0)
    server.start()
    try:
        base = f"http://localhost:{server.port}"
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(f"{base}/nonexistent.html")
        assert exc_info.value.code == 404
    finally:
        server.stop()


def test_server_port_attribute(sample_site: Path):
    from tests.benchmark.mock_site.server import MockSiteServer

    server = MockSiteServer(root_dir=sample_site, port=0)
    server.start()
    try:
        assert isinstance(server.port, int)
        assert server.port > 0
    finally:
        server.stop()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/benchmark/test_mock_server.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# tests/benchmark/mock_site/__init__.py
"""Mock website for benchmark testing."""
```

```python
# tests/benchmark/mock_site/server.py
"""Lightweight static file server for benchmark mock website."""

from __future__ import annotations

import http.server
import threading
from functools import partial
from pathlib import Path


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


class MockSiteServer:
    def __init__(self, root_dir: Path | None = None, port: int = 0) -> None:
        self._root_dir = root_dir or (Path(__file__).parent / "scenarios")
        self._requested_port = port
        self._httpd: http.server.HTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        if self._httpd is None:
            raise RuntimeError("Server not started")
        return self._httpd.server_address[1]

    def start(self) -> None:
        handler = partial(_QuietHandler, directory=str(self._root_dir))
        self._httpd = http.server.HTTPServer(
            ("127.0.0.1", self._requested_port), handler,
        )
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/benchmark/test_mock_server.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tests/benchmark/mock_site/ tests/benchmark/test_mock_server.py
git commit -m "feat(benchmark): add mock site static file server"
```

---

## Task 3: 指标计算引擎

**Files:**
- Create: `tests/benchmark/metrics.py`
- Test: `tests/benchmark/test_metrics.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/benchmark/test_metrics.py
"""Test benchmark metrics calculations."""


def test_exact_match():
    from tests.benchmark.metrics import field_match
    assert field_match("Apple", "Apple", strategy="exact") is True
    assert field_match("Apple", "apple", strategy="exact") is False
    assert field_match("  Apple  ", "Apple", strategy="exact") is True


def test_numeric_tolerance():
    from tests.benchmark.metrics import field_match
    assert field_match("99.99", "99.99", strategy="numeric_tolerance") is True
    assert field_match("99.99", "100.00", strategy="numeric_tolerance") is False
    assert field_match("99.995", "99.99", strategy="numeric_tolerance") is True


def test_fuzzy_match():
    from tests.benchmark.metrics import field_match
    assert field_match(
        "6.9英寸 AMOLED, 骁龙8 Gen4",
        "6.9英寸 AMOLED, 骁龙8 Gen4, 12GB RAM",
        strategy="fuzzy",
    ) is True
    assert field_match("完全不同的文本", "另一段文字", strategy="fuzzy") is False


def test_contains_match():
    from tests.benchmark.metrics import field_match
    assert field_match("包含关键词的长文本", "关键词", strategy="contains") is True
    assert field_match("不包含的文本", "缺失内容", strategy="contains") is False


def test_precision_recall_f1():
    from tests.benchmark.metrics import precision_recall_f1
    p, r, f1 = precision_recall_f1(tp=8, fp=2, fn=2)
    assert abs(p - 0.8) < 1e-6
    assert abs(r - 0.8) < 1e-6
    assert abs(f1 - 0.8) < 1e-6


def test_precision_recall_f1_zero():
    from tests.benchmark.metrics import precision_recall_f1
    p, r, f1 = precision_recall_f1(tp=0, fp=0, fn=0)
    assert p == 0.0
    assert r == 0.0
    assert f1 == 0.0


def test_compute_record_metrics():
    from tests.benchmark.metrics import compute_record_metrics

    actual = [
        {"name": "A", "price": "100"},
        {"name": "B", "price": "200"},
        {"name": "C", "price": "999"},
    ]
    expected = [
        {"name": "A", "price": "100"},
        {"name": "B", "price": "200"},
        {"name": "D", "price": "400"},
    ]
    metrics = compute_record_metrics(actual=actual, expected=expected, match_key="name")
    assert metrics.matched == 2
    assert metrics.actual_total == 3
    assert metrics.expected_total == 3
    assert abs(metrics.precision - 2 / 3) < 1e-6
    assert abs(metrics.recall - 2 / 3) < 1e-6


def test_compute_field_metrics():
    from tests.benchmark.metrics import compute_field_metrics

    matched_pairs = [
        ({"name": "A", "price": "100"}, {"name": "A", "price": "100"}),
        ({"name": "B", "price": "999"}, {"name": "B", "price": "200"}),
    ]
    field_strategies = {"name": "exact", "price": "exact"}
    field_results = compute_field_metrics(matched_pairs, field_strategies)
    assert abs(field_results["name"].f1 - 1.0) < 1e-6
    assert abs(field_results["price"].precision - 0.5) < 1e-6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/benchmark/test_metrics.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# tests/benchmark/metrics.py
"""Benchmark metrics computation."""

from __future__ import annotations
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any


def field_match(
    actual_value: str | None,
    expected_value: str | None,
    *,
    strategy: str = "exact",
    numeric_tolerance: float = 0.01,
    fuzzy_threshold: float = 0.85,
) -> bool:
    if actual_value is None or expected_value is None:
        return actual_value is None and expected_value is None
    a = str(actual_value).strip()
    e = str(expected_value).strip()
    if strategy == "exact":
        return a == e
    if strategy == "numeric_tolerance":
        try:
            return abs(float(a) - float(e)) <= numeric_tolerance
        except (ValueError, TypeError):
            return a == e
    if strategy == "fuzzy":
        return SequenceMatcher(None, a, e).ratio() >= fuzzy_threshold
    if strategy == "contains":
        return e in a
    return a == e


def precision_recall_f1(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return precision, recall, f1


@dataclass
class RecordMetrics:
    matched: int
    actual_total: int
    expected_total: int
    precision: float
    recall: float
    f1: float
    unmatched_actual: list[dict[str, Any]]
    unmatched_expected: list[dict[str, Any]]


def compute_record_metrics(
    *, actual: list[dict[str, Any]], expected: list[dict[str, Any]], match_key: str,
) -> RecordMetrics:
    expected_by_key = {str(r.get(match_key, "")).strip(): r for r in expected if r.get(match_key)}
    matched = 0
    unmatched_actual = []
    matched_keys: set[str] = set()
    for rec in actual:
        key = str(rec.get(match_key, "")).strip()
        if key in expected_by_key:
            matched += 1
            matched_keys.add(key)
        else:
            unmatched_actual.append(rec)
    unmatched_expected = [r for r in expected if str(r.get(match_key, "")).strip() not in matched_keys]
    p, r, f1 = precision_recall_f1(matched, len(actual) - matched, len(expected) - matched)
    return RecordMetrics(matched=matched, actual_total=len(actual), expected_total=len(expected),
                         precision=p, recall=r, f1=f1,
                         unmatched_actual=unmatched_actual, unmatched_expected=unmatched_expected)


@dataclass
class FieldMetrics:
    field_name: str
    correct: int
    total: int
    precision: float
    recall: float
    f1: float


def compute_field_metrics(
    matched_pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    field_strategies: dict[str, str],
) -> dict[str, FieldMetrics]:
    results = {}
    for field_name, strategy in field_strategies.items():
        correct = sum(
            1 for a, e in matched_pairs
            if field_match(a.get(field_name), e.get(field_name), strategy=strategy)
        )
        total = len(matched_pairs)
        tp, fp, fn = correct, total - correct, total - correct
        p, r, f1 = precision_recall_f1(tp, fp, fn)
        results[field_name] = FieldMetrics(field_name=field_name, correct=correct, total=total,
                                           precision=p, recall=r, f1=f1)
    return results


def aggregate_field_f1(field_results: dict[str, FieldMetrics]) -> float:
    if not field_results:
        return 0.0
    total_weight = sum(fm.total for fm in field_results.values())
    if total_weight == 0:
        return 0.0
    return sum(fm.f1 * fm.total for fm in field_results.values()) / total_weight
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/benchmark/test_metrics.py -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tests/benchmark/metrics.py tests/benchmark/test_metrics.py
git commit -m "feat(benchmark): add metrics computation engine"
```

---

## Task 4: 评估引擎

**Files:**
- Create: `tests/benchmark/evaluator.py`
- Test: `tests/benchmark/test_evaluator.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/benchmark/test_evaluator.py
"""Test benchmark evaluator — orchestrates record + field metrics."""
import json
from pathlib import Path

import pytest


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


@pytest.fixture()
def ground_truth_file(tmp_path: Path) -> Path:
    records = [
        {"product_name": "Galaxy S25", "price": 9999.0, "brand": "Samsung"},
        {"product_name": "iPhone 16", "price": 8999.0, "brand": "Apple"},
        {"product_name": "Pixel 9", "price": 6999.0, "brand": "Google"},
    ]
    gt_path = tmp_path / "gt.jsonl"
    _write_jsonl(gt_path, records)
    return gt_path


@pytest.fixture()
def actual_results_file(tmp_path: Path) -> Path:
    records = [
        {"product_name": "Galaxy S25", "price": 9999.0, "brand": "Samsung"},
        {"product_name": "iPhone 16", "price": 9000.0, "brand": "Apple"},  # price slightly off
        {"product_name": "Unknown", "price": 1000.0, "brand": "NoName"},  # not in GT
    ]
    result_path = tmp_path / "actual.jsonl"
    _write_jsonl(result_path, records)
    return result_path


def test_evaluate_scenario_full(ground_truth_file: Path, actual_results_file: Path):
    """Full evaluation pipeline should produce ScenarioResult."""
    from tests.benchmark.evaluator import evaluate_scenario, EvaluationParams

    params = EvaluationParams(
        match_key="product_name",
        field_matching={"product_name": "exact", "price": "numeric_tolerance", "brand": "exact"},
        thresholds={"min_record_recall": 0.5, "min_field_f1": 0.5, "max_steps": 100},
    )
    result = evaluate_scenario(
        actual_file=actual_results_file,
        ground_truth_file=ground_truth_file,
        params=params,
    )

    assert result.record_metrics.matched == 2
    assert result.record_metrics.expected_total == 3
    assert result.record_metrics.actual_total == 3
    assert "product_name" in result.field_metrics
    assert "price" in result.field_metrics
    assert "brand" in result.field_metrics
    assert abs(result.field_metrics["product_name"].f1 - 1.0) < 1e-6
    assert abs(result.field_metrics["brand"].f1 - 1.0) < 1e-6
    assert result.field_metrics["price"].correct == 1
    assert result.overall_field_f1 > 0


def test_evaluate_empty_actual(ground_truth_file: Path, tmp_path: Path):
    """Empty actual file should produce zero metrics without crash."""
    from tests.benchmark.evaluator import evaluate_scenario, EvaluationParams

    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")

    params = EvaluationParams(
        match_key="product_name",
        field_matching={"product_name": "exact"},
        thresholds={"min_record_recall": 0.5, "min_field_f1": 0.5, "max_steps": 100},
    )
    result = evaluate_scenario(actual_file=empty, ground_truth_file=ground_truth_file, params=params)
    assert result.record_metrics.matched == 0
    assert result.record_metrics.recall == 0.0


def test_pass_fail_judgment(ground_truth_file: Path, actual_results_file: Path):
    """Scenario should fail if metrics fall below thresholds."""
    from tests.benchmark.evaluator import evaluate_scenario, EvaluationParams

    params = EvaluationParams(
        match_key="product_name",
        field_matching={"product_name": "exact", "price": "exact", "brand": "exact"},
        thresholds={"min_record_recall": 0.99, "min_field_f1": 0.99, "max_steps": 10},
    )
    result = evaluate_scenario(
        actual_file=actual_results_file,
        ground_truth_file=ground_truth_file,
        params=params,
    )
    assert result.passed is False
    assert len(result.failure_reasons) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/benchmark/test_evaluator.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# tests/benchmark/evaluator.py
"""Benchmark evaluator — orchestrates record and field metrics to judge a scenario."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .metrics import (
    RecordMetrics, FieldMetrics, aggregate_field_f1,
    compute_field_metrics, compute_record_metrics,
)


@dataclass
class EvaluationParams:
    match_key: str
    field_matching: dict[str, str]
    thresholds: dict[str, float]


@dataclass
class ScenarioResult:
    record_metrics: RecordMetrics
    field_metrics: dict[str, FieldMetrics]
    overall_field_f1: float
    exact_match_rate: float
    passed: bool
    failure_reasons: list[str] = field(default_factory=list)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not path.exists():
        return records
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _build_matched_pairs(
    actual: list[dict[str, Any]], expected: list[dict[str, Any]], match_key: str,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    expected_by_key = {}
    for rec in expected:
        key = str(rec.get(match_key, "")).strip()
        if key:
            expected_by_key[key] = rec
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for rec in actual:
        key = str(rec.get(match_key, "")).strip()
        if key in expected_by_key:
            pairs.append((rec, expected_by_key[key]))
    return pairs


def evaluate_scenario(
    *, actual_file: Path, ground_truth_file: Path, params: EvaluationParams,
    efficiency_metrics: dict[str, Any] | None = None,
) -> ScenarioResult:
    actual = _load_jsonl(actual_file)
    expected = _load_jsonl(ground_truth_file)

    record_metrics = compute_record_metrics(actual=actual, expected=expected, match_key=params.match_key)
    matched_pairs = _build_matched_pairs(actual, expected, params.match_key)

    if params.field_matching and matched_pairs:
        field_metrics = compute_field_metrics(matched_pairs, params.field_matching)
    else:
        field_metrics = {}

    overall_field_f1 = aggregate_field_f1(field_metrics)

    exact_matches = 0
    for actual_rec, expected_rec in matched_pairs:
        all_correct = True
        for fname, strategy in params.field_matching.items():
            from .metrics import field_match
            if not field_match(actual_rec.get(fname), expected_rec.get(fname), strategy=strategy):
                all_correct = False
                break
        if all_correct:
            exact_matches += 1
    exact_match_rate = exact_matches / len(matched_pairs) if matched_pairs else 0.0

    thresholds = params.thresholds
    failure_reasons: list[str] = []
    min_recall = float(thresholds.get("min_record_recall", 0.0))
    if record_metrics.recall < min_recall:
        failure_reasons.append(f"record_recall={record_metrics.recall:.3f} < {min_recall}")
    min_f1 = float(thresholds.get("min_field_f1", 0.0))
    if overall_field_f1 < min_f1:
        failure_reasons.append(f"field_f1={overall_field_f1:.3f} < {min_f1}")
    max_steps = int(thresholds.get("max_steps", 9999))
    if efficiency_metrics:
        steps = int(efficiency_metrics.get("total_graph_steps", 0))
        if steps > max_steps:
            failure_reasons.append(f"total_graph_steps={steps} > {max_steps}")

    return ScenarioResult(
        record_metrics=record_metrics, field_metrics=field_metrics,
        overall_field_f1=overall_field_f1, exact_match_rate=exact_match_rate,
        passed=len(failure_reasons) == 0, failure_reasons=failure_reasons,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/benchmark/test_evaluator.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tests/benchmark/evaluator.py tests/benchmark/test_evaluator.py
git commit -m "feat(benchmark): add evaluation engine"
```

---

## Task 5: 模拟网站页面 — 共享资源 + 场景1（Products）

**Files:**
- Create: `tests/benchmark/mock_site/shared/style.css`
- Create: `tests/benchmark/mock_site/shared/pagination.js`
- Create: `tests/benchmark/mock_site/shared/dynamic_load.js`
- Create: `tests/benchmark/mock_site/shared/tabs.js`
- Create: `tests/benchmark/mock_site/scenarios/products/index.html`
- Create: `tests/benchmark/mock_site/scenarios/products/detail_1.html` ~ `detail_15.html`
- Create: `tests/benchmark/mock_site/generate_products.py`
- Test: `tests/benchmark/test_mock_site_products.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/benchmark/test_mock_site_products.py
"""Verify products scenario pages are properly served and structured."""
import urllib.request
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def products_server():
    from tests.benchmark.mock_site.server import MockSiteServer
    root = Path(__file__).parent / "mock_site"
    server = MockSiteServer(root_dir=root, port=0)
    server.start()
    yield server
    server.stop()


def test_products_index_page_exists(products_server):
    base = f"http://localhost:{products_server.port}"
    resp = urllib.request.urlopen(f"{base}/scenarios/products/index.html")
    assert resp.status == 200
    body = resp.read().decode()
    assert "detail_1.html" in body
    assert "page" in body.lower() or "pagination" in body.lower() or "下一页" in body


def test_products_detail_page_has_fields(products_server):
    base = f"http://localhost:{products_server.port}"
    resp = urllib.request.urlopen(f"{base}/scenarios/products/detail_1.html")
    assert resp.status == 200
    body = resp.read().decode()
    assert "product-name" in body or "product_name" in body
    assert "price" in body
    assert "brand" in body


def test_products_all_15_detail_pages_exist(products_server):
    base = f"http://localhost:{products_server.port}"
    for i in range(1, 16):
        resp = urllib.request.urlopen(f"{base}/scenarios/products/detail_{i}.html")
        assert resp.status == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/benchmark/test_mock_site_products.py -v`
Expected: FAIL — 404 errors

- [ ] **Step 3: Create shared resources**

Create `tests/benchmark/mock_site/shared/style.css`:
```css
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Microsoft YaHei', sans-serif; background: #f5f5f5; color: #333; padding: 20px; }
.container { max-width: 1200px; margin: 0 auto; }
h1 { font-size: 24px; margin-bottom: 20px; color: #1a1a1a; }
.product-list { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 20px; }
.product-card { background: #fff; border: 1px solid #e0e0e0; border-radius: 8px; padding: 16px; }
.product-card a { text-decoration: none; color: #1a73e8; font-weight: bold; }
.product-card .price { color: #e53935; font-size: 18px; margin-top: 8px; }
.detail-container { background: #fff; border-radius: 8px; padding: 24px; max-width: 800px; margin: 0 auto; }
.detail-field { margin-bottom: 12px; }
.detail-field .label { font-weight: bold; color: #666; display: inline-block; width: 100px; }
.detail-field .value { color: #333; }
.pagination { display: flex; gap: 8px; margin-top: 24px; justify-content: center; }
.pagination a, .pagination span { padding: 8px 14px; border: 1px solid #ddd; border-radius: 4px; text-decoration: none; color: #333; }
.pagination .active { background: #1a73e8; color: #fff; border-color: #1a73e8; }
.tab-nav { display: flex; gap: 4px; margin-bottom: 16px; }
.tab-nav button { padding: 10px 20px; border: 1px solid #ddd; background: #fff; cursor: pointer; border-radius: 4px 4px 0 0; }
.tab-nav button.active { background: #1a73e8; color: #fff; border-color: #1a73e8; }
.tab-content { display: none; }
.tab-content.active { display: block; }
.tree-nav ul { list-style: none; padding-left: 20px; }
.tree-nav > ul { padding-left: 0; }
.tree-nav li { margin: 4px 0; }
.tree-nav a { text-decoration: none; color: #1a73e8; }
.tree-nav .toggle { cursor: pointer; user-select: none; margin-right: 4px; }
.load-more-btn { display: block; margin: 20px auto; padding: 10px 30px; background: #1a73e8; color: #fff; border: none; border-radius: 4px; cursor: pointer; font-size: 16px; }
.collapsible-header { cursor: pointer; background: #f0f0f0; padding: 10px; border-radius: 4px; margin-top: 12px; }
.collapsible-content { display: none; padding: 10px; }
.collapsible-content.expanded { display: block; }
```

Create `tests/benchmark/mock_site/shared/pagination.js`:
```javascript
document.addEventListener('DOMContentLoaded', function() {
    const items = document.querySelectorAll('.product-item');
    const pageSize = parseInt(document.body.dataset.pageSize || '5');
    const paginationEl = document.querySelector('.pagination');
    if (!items.length || !paginationEl) return;
    const totalPages = Math.ceil(items.length / pageSize);
    let currentPage = 1;
    function renderPage(page) {
        currentPage = page;
        items.forEach(function(item, idx) {
            const start = (page - 1) * pageSize;
            item.style.display = (idx >= start && idx < start + pageSize) ? '' : 'none';
        });
        renderPagination();
    }
    function renderPagination() {
        var html = '';
        if (currentPage > 1) html += '<a href="#" data-page="' + (currentPage-1) + '">上一页</a>';
        for (var i = 1; i <= totalPages; i++) {
            if (i === currentPage) html += '<span class="active">' + i + '</span>';
            else html += '<a href="#" data-page="' + i + '">' + i + '</a>';
        }
        if (currentPage < totalPages) html += '<a href="#" data-page="' + (currentPage+1) + '">下一页</a>';
        paginationEl.innerHTML = html;
        paginationEl.querySelectorAll('a').forEach(function(a) {
            a.addEventListener('click', function(e) { e.preventDefault(); renderPage(parseInt(this.dataset.page)); });
        });
    }
    renderPage(1);
});
```

Create `tests/benchmark/mock_site/shared/dynamic_load.js`:
```javascript
document.addEventListener('DOMContentLoaded', function() {
    var loadBtn = document.querySelector('.load-more-btn');
    if (loadBtn) {
        var hiddenGroups = document.querySelectorAll('.load-group.hidden');
        var groupIndex = 0;
        loadBtn.addEventListener('click', function() {
            if (groupIndex < hiddenGroups.length) {
                hiddenGroups[groupIndex].classList.remove('hidden');
                hiddenGroups[groupIndex].style.display = '';
                groupIndex++;
                if (groupIndex >= hiddenGroups.length) loadBtn.style.display = 'none';
            }
        });
    }
    document.querySelectorAll('.collapsible-header').forEach(function(header) {
        header.addEventListener('click', function() {
            var content = this.nextElementSibling;
            if (content && content.classList.contains('collapsible-content')) {
                content.classList.toggle('expanded');
            }
        });
    });
});
```

Create `tests/benchmark/mock_site/shared/tabs.js`:
```javascript
document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('.tab-nav button').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var targetId = this.dataset.tab;
            this.parentElement.querySelectorAll('button').forEach(function(b) { b.classList.remove('active'); });
            document.querySelectorAll('.tab-content').forEach(function(c) { c.classList.remove('active'); });
            this.classList.add('active');
            var target = document.getElementById(targetId);
            if (target) target.classList.add('active');
        });
    });
});
```

- [ ] **Step 4: Create products page generator and run it**

Create `tests/benchmark/mock_site/generate_products.py` with 15 products data, then:

```bash
python tests/benchmark/mock_site/generate_products.py
```

See full generator code in spec. Products list:
Galaxy S25 Ultra (¥9999), iPhone 16 Pro (¥8999), Pixel 9 Pro (¥6999), Xiaomi 15 Pro (¥4999), OnePlus 13 (¥4499), ThinkPad X1 Carbon (¥12999), MacBook Pro 16 (¥19999), Dell XPS 15 (¥10999), ROG Zephyrus G16 (¥13999), Surface Pro 11 (¥8999), AirPods Pro 3 (¥1899), Sony WH-1000XM6 (¥2499), Logitech MX Master 4 (¥799), Samsung T9 SSD 2TB (¥1299), Anker 737 充电器 (¥499).

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/benchmark/test_mock_site_products.py -v`
Expected: All 3 tests PASS

- [ ] **Step 6: Commit**

```bash
git add tests/benchmark/mock_site/shared/ tests/benchmark/mock_site/scenarios/products/ tests/benchmark/mock_site/generate_products.py tests/benchmark/test_mock_site_products.py
git commit -m "feat(benchmark): add shared resources and products scenario pages"
```

---

## Task 6: 场景 YAML 定义 + Ground Truth 数据（Products）

**Files:**
- Create: `tests/benchmark/scenarios/products.yaml`
- Create: `tests/benchmark/ground_truth/products.jsonl`
- Test: `tests/benchmark/test_scenario_data.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/benchmark/test_scenario_data.py
"""Verify scenario YAML and ground truth files are consistent."""
import json
from pathlib import Path

BENCHMARK_DIR = Path(__file__).parent


def test_products_yaml_loads():
    from tests.benchmark.scenarios.schema import load_scenario
    config = load_scenario("products")
    assert config.scenario.id == "products"
    assert config.ground_truth.record_count == 15
    assert len(config.ground_truth.fields) >= 3


def test_products_ground_truth_has_correct_count():
    gt_path = BENCHMARK_DIR / "ground_truth" / "products.jsonl"
    assert gt_path.exists()
    records = [json.loads(l) for l in gt_path.read_text("utf-8").splitlines() if l.strip()]
    assert len(records) == 15


def test_products_ground_truth_fields_not_empty():
    gt_path = BENCHMARK_DIR / "ground_truth" / "products.jsonl"
    with open(gt_path, "r", encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if not line.strip(): continue
            rec = json.loads(line)
            assert rec.get("product_name"), f"Record {n}: product_name empty"
            assert rec.get("price") is not None, f"Record {n}: price None"
            assert rec.get("brand"), f"Record {n}: brand empty"


def test_products_ground_truth_unique_keys():
    gt_path = BENCHMARK_DIR / "ground_truth" / "products.jsonl"
    names = [json.loads(l)["product_name"] for l in gt_path.read_text("utf-8").splitlines() if l.strip()]
    assert len(names) == len(set(names))
```

- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Create products.yaml** (see spec for full content)
- [ ] **Step 4: Create products.jsonl** (15 records matching generate_products.py data)
- [ ] **Step 5: Run test to verify it passes**
- [ ] **Step 6: Commit**

```bash
git add tests/benchmark/scenarios/products.yaml tests/benchmark/ground_truth/products.jsonl tests/benchmark/test_scenario_data.py
git commit -m "feat(benchmark): add products scenario YAML and ground truth"
```

---

## Task 7: 模拟网站页面 — 场景 2~5

**Files:**
- Create: `tests/benchmark/mock_site/generate_all.py`
- Create: `tests/benchmark/mock_site/scenarios/categories/`
- Create: `tests/benchmark/mock_site/scenarios/dynamic/`
- Create: `tests/benchmark/mock_site/scenarios/variants/`
- Create: `tests/benchmark/mock_site/scenarios/nested/`
- Test: `tests/benchmark/test_mock_site_all.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/benchmark/test_mock_site_all.py
"""Verify all scenario pages are served and structurally correct."""
import urllib.request
from pathlib import Path
import pytest

@pytest.fixture(scope="module")
def site_server():
    from tests.benchmark.mock_site.server import MockSiteServer
    root = Path(__file__).parent / "mock_site"
    server = MockSiteServer(root_dir=root, port=0)
    server.start()
    yield server
    server.stop()

def test_categories_index(site_server):
    base = f"http://localhost:{site_server.port}"
    resp = urllib.request.urlopen(f"{base}/scenarios/categories/index.html")
    body = resp.read().decode()
    assert resp.status == 200
    assert "tab-nav" in body or "tab_nav" in body
    for cat in ["手机", "电脑", "配件"]:
        assert cat in body

def test_categories_detail_pages(site_server):
    base = f"http://localhost:{site_server.port}"
    for i in range(1, 16):
        resp = urllib.request.urlopen(f"{base}/scenarios/categories/detail_{i}.html")
        assert resp.status == 200

def test_dynamic_index(site_server):
    base = f"http://localhost:{site_server.port}"
    resp = urllib.request.urlopen(f"{base}/scenarios/dynamic/index.html")
    body = resp.read().decode()
    assert resp.status == 200
    assert "load-more-btn" in body or "加载更多" in body

def test_dynamic_detail_has_collapsible(site_server):
    base = f"http://localhost:{site_server.port}"
    resp = urllib.request.urlopen(f"{base}/scenarios/dynamic/detail_1.html")
    body = resp.read().decode()
    assert "collapsible" in body

def test_dynamic_all_details(site_server):
    base = f"http://localhost:{site_server.port}"
    for i in range(1, 10):
        resp = urllib.request.urlopen(f"{base}/scenarios/dynamic/detail_{i}.html")
        assert resp.status == 200

def test_variants_index(site_server):
    base = f"http://localhost:{site_server.port}"
    resp = urllib.request.urlopen(f"{base}/scenarios/variants/index.html")
    body = resp.read().decode()
    assert "card_" in body or "table_" in body

def test_variants_card_and_table_pages(site_server):
    base = f"http://localhost:{site_server.port}"
    for i in range(1, 6):
        resp = urllib.request.urlopen(f"{base}/scenarios/variants/card_{i}.html")
        assert resp.status == 200
    for i in range(1, 6):
        resp = urllib.request.urlopen(f"{base}/scenarios/variants/table_{i}.html")
        assert resp.status == 200

def test_nested_index(site_server):
    base = f"http://localhost:{site_server.port}"
    resp = urllib.request.urlopen(f"{base}/scenarios/nested/index.html")
    body = resp.read().decode()
    assert "tree-nav" in body or "tree_nav" in body

def test_nested_list_pages(site_server):
    base = f"http://localhost:{site_server.port}"
    for i in range(1, 5):
        resp = urllib.request.urlopen(f"{base}/scenarios/nested/list_{i}.html")
        assert resp.status == 200

def test_nested_detail_pages(site_server):
    base = f"http://localhost:{site_server.port}"
    for i in range(1, 13):
        resp = urllib.request.urlopen(f"{base}/scenarios/nested/detail_{i}.html")
        assert resp.status == 200
```

- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Create generate_all.py** with categories (3 tabs × 5 products), dynamic (9 items, load-more + collapsible), variants (5 card + 5 table), nested (3-level tree, 4 leaf lists × 3 items = 12)
- [ ] **Step 4: Run generator and verify tests pass**

```bash
python tests/benchmark/mock_site/generate_all.py
pytest tests/benchmark/test_mock_site_all.py -v
```

- [ ] **Step 5: Commit**

```bash
git add tests/benchmark/mock_site/generate_all.py tests/benchmark/mock_site/scenarios/ tests/benchmark/test_mock_site_all.py
git commit -m "feat(benchmark): add categories/dynamic/variants/nested scenario pages"
```

---

## Task 8: 其余 4 个场景的 YAML + Ground Truth

**Files:**
- Create: `tests/benchmark/scenarios/categories.yaml` (15 records, match_key=product_name)
- Create: `tests/benchmark/scenarios/dynamic.yaml` (9 records, includes hidden_specs)
- Create: `tests/benchmark/scenarios/variants.yaml` (10 records, card+table layouts)
- Create: `tests/benchmark/scenarios/nested.yaml` (12 records, 4 leaf categories)
- Create: `tests/benchmark/ground_truth/categories.jsonl`
- Create: `tests/benchmark/ground_truth/dynamic.jsonl`
- Create: `tests/benchmark/ground_truth/variants.jsonl`
- Create: `tests/benchmark/ground_truth/nested.jsonl`
- Test: `tests/benchmark/test_all_scenario_data.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/benchmark/test_all_scenario_data.py
"""Verify all scenario YAML + ground truth files are consistent."""
import json
from pathlib import Path
import pytest

BENCHMARK_DIR = Path(__file__).parent
SCENARIOS = ["products", "categories", "dynamic", "variants", "nested"]

@pytest.mark.parametrize("scenario_id", SCENARIOS)
def test_yaml_loads(scenario_id):
    from tests.benchmark.scenarios.schema import load_scenario
    config = load_scenario(scenario_id)
    assert config.scenario.id == scenario_id

@pytest.mark.parametrize("scenario_id", SCENARIOS)
def test_ground_truth_count_matches_yaml(scenario_id):
    from tests.benchmark.scenarios.schema import load_scenario
    config = load_scenario(scenario_id)
    gt_path = BENCHMARK_DIR / config.ground_truth.file
    assert gt_path.exists()
    records = [json.loads(l) for l in gt_path.read_text("utf-8").splitlines() if l.strip()]
    assert len(records) == config.ground_truth.record_count

@pytest.mark.parametrize("scenario_id", SCENARIOS)
def test_ground_truth_match_key_unique(scenario_id):
    from tests.benchmark.scenarios.schema import load_scenario
    config = load_scenario(scenario_id)
    gt_path = BENCHMARK_DIR / config.ground_truth.file
    records = [json.loads(l) for l in gt_path.read_text("utf-8").splitlines() if l.strip()]
    keys = [str(r.get(config.evaluation.match_key, "")).strip() for r in records]
    assert len(keys) == len(set(keys))

@pytest.mark.parametrize("scenario_id", SCENARIOS)
def test_list_scenarios_includes(scenario_id):
    from tests.benchmark.scenarios.schema import list_scenarios
    assert scenario_id in list_scenarios()
```

- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3~6: Create all YAML + JSONL files** (see full data in previous session context)
- [ ] **Step 7: Run tests**

```bash
pytest tests/benchmark/test_all_scenario_data.py -v
```

Expected: All 20 tests PASS

- [ ] **Step 8: Commit**

```bash
git add tests/benchmark/scenarios/*.yaml tests/benchmark/ground_truth/*.jsonl tests/benchmark/test_all_scenario_data.py
git commit -m "feat(benchmark): add all scenario YAML definitions and ground truth data"
```

---

## Task 9: 报告生成器

**Files:**
- Create: `tests/benchmark/reporter.py`
- Test: `tests/benchmark/test_reporter.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/benchmark/test_reporter.py
"""Test benchmark report generation (JSON + Markdown)."""
import json
from pathlib import Path
from tests.benchmark.metrics import RecordMetrics, FieldMetrics


def _make_scenario_result(scenario_id: str, passed: bool = True):
    from tests.benchmark.evaluator import ScenarioResult
    return ScenarioResult(
        record_metrics=RecordMetrics(
            matched=12, actual_total=14, expected_total=15,
            precision=12/14, recall=12/15, f1=0.857,
            unmatched_actual=[{"name": "X"}], unmatched_expected=[{"name": "Y"}, {"name": "Z"}],
        ),
        field_metrics={
            "product_name": FieldMetrics(field_name="product_name", correct=12, total=12, precision=1.0, recall=1.0, f1=1.0),
            "price": FieldMetrics(field_name="price", correct=10, total=12, precision=0.833, recall=0.833, f1=0.833),
        },
        overall_field_f1=0.916, exact_match_rate=0.75,
        passed=passed, failure_reasons=[] if passed else ["record_recall=0.800 < 0.900"],
    )


def test_generate_json_report(tmp_path: Path):
    from tests.benchmark.reporter import generate_json_report
    results = {"products": _make_scenario_result("products", True), "categories": _make_scenario_result("categories", False)}
    efficiency = {"products": {"total_graph_steps": 23}, "categories": {"total_graph_steps": 35}}
    output_path = tmp_path / "report.json"
    generate_json_report(results, efficiency_data=efficiency, output_path=output_path, git_commit="abc1234")
    report = json.loads(output_path.read_text("utf-8"))
    assert report["git_commit"] == "abc1234"
    assert report["scenarios"]["products"]["status"] == "pass"
    assert report["scenarios"]["categories"]["status"] == "fail"
    assert report["overall"]["scenarios_passed"] == 1


def test_generate_markdown_report(tmp_path: Path):
    from tests.benchmark.reporter import generate_markdown_report
    results = {"products": _make_scenario_result("products", True)}
    output_path = tmp_path / "report.md"
    generate_markdown_report(results, output_path=output_path)
    content = output_path.read_text("utf-8")
    assert "products" in content
    assert "F1" in content


def test_compare_reports(tmp_path: Path):
    from tests.benchmark.reporter import generate_json_report, compare_reports
    results = {"products": _make_scenario_result("products", True)}
    eff = {"products": {"total_graph_steps": 23}}
    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    generate_json_report(results, efficiency_data=eff, output_path=old_path, git_commit="old123")
    generate_json_report(results, efficiency_data=eff, output_path=new_path, git_commit="new456")
    diff = compare_reports(old_path, new_path)
    assert "products" in diff
```

- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Write reporter.py** — `generate_json_report`, `generate_markdown_report`, `compare_reports`
- [ ] **Step 4: Run test to verify it passes**
- [ ] **Step 5: Commit**

```bash
git add tests/benchmark/reporter.py tests/benchmark/test_reporter.py
git commit -m "feat(benchmark): add JSON and Markdown report generator"
```

---

## Task 10: 基准测试运行器

**Files:**
- Create: `tests/benchmark/runner.py`
- Test: `tests/benchmark/test_runner.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/benchmark/test_runner.py
"""Test benchmark runner — scenario orchestration (unit-level, no real AutoSpider)."""
import json
from pathlib import Path
from unittest.mock import patch

def _create_fake_result_jsonl(output_dir: Path, records: list[dict]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    result_file = output_dir / "merged_results.jsonl"
    with open(result_file, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return result_file

def test_runner_run_scenario_with_mock(tmp_path: Path):
    from tests.benchmark.runner import BenchmarkRunner, ScenarioRunResult
    scenarios_dir = tmp_path / "scenarios"
    scenarios_dir.mkdir()
    gt_dir = tmp_path / "ground_truth"
    gt_dir.mkdir()
    out_dir = tmp_path / "output"
    yaml_content = f"""
scenario:
  id: test_run
  name: Test
  description: Test runner
task:
  request: "采集 {{base_url}}/test/"
  cli_overrides:
    output_dir: "{str(out_dir).replace(chr(92), '/')}"
ground_truth:
  file: "ground_truth/test_run.jsonl"
  record_count: 2
  fields:
    - name: "name"
      type: "text"
evaluation:
  match_key: "name"
  field_matching:
    name: exact
  thresholds:
    min_record_recall: 0.5
    min_field_f1: 0.5
    max_steps: 100
"""
    (scenarios_dir / "test_run.yaml").write_text(yaml_content, encoding="utf-8")
    (gt_dir / "test_run.jsonl").write_text('{{"name": "A"}}\n{{"name": "B"}}\n', encoding="utf-8")
    _create_fake_result_jsonl(out_dir, [{"name": "A"}, {"name": "B"}])
    runner = BenchmarkRunner(scenarios_dir=scenarios_dir, ground_truth_dir=gt_dir, base_url="http://localhost:9999")
    with patch.object(runner, "_invoke_autospider", return_value={"status": "completed"}):
        result = runner.run_scenario("test_run")
    assert isinstance(result, ScenarioRunResult)
    assert result.evaluation_result.passed is True
    assert result.evaluation_result.record_metrics.matched == 2

def test_runner_list_scenarios(tmp_path: Path):
    from tests.benchmark.runner import BenchmarkRunner
    scenarios_dir = tmp_path / "scenarios"
    scenarios_dir.mkdir()
    (scenarios_dir / "a.yaml").write_text("""
scenario:
  id: a
  name: A
  description: A
task:
  request: test
ground_truth:
  file: gt.jsonl
  record_count: 1
  fields: []
evaluation:
  match_key: name
  field_matching: {}
  thresholds:
    min_record_recall: 0.5
    min_field_f1: 0.5
    max_steps: 99
""", encoding="utf-8")
    runner = BenchmarkRunner(scenarios_dir=scenarios_dir, ground_truth_dir=tmp_path, base_url="http://localhost:9999")
    assert "a" in runner.list_scenarios()
```

- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Write runner.py** — `BenchmarkRunner` with `run_scenario`, `run_all`, `_invoke_autospider` (subprocess), `_find_result_file`
- [ ] **Step 4: Run test to verify it passes**
- [ ] **Step 5: Commit**

```bash
git add tests/benchmark/runner.py tests/benchmark/test_runner.py
git commit -m "feat(benchmark): add benchmark runner with scenario orchestration"
```

---

## Task 11: pytest conftest + test 入口 + CLI 集成

**Files:**
- Create: `tests/benchmark/conftest.py`
- Create: `tests/benchmark/test_benchmark.py`
- Modify: `src/autospider/cli.py` — add `benchmark` command
- Modify: `.gitignore` — add `tests/benchmark/reports/`

- [ ] **Step 1: Create conftest.py**

```python
# tests/benchmark/conftest.py
"""pytest fixtures for benchmark tests."""
from __future__ import annotations
from pathlib import Path
import pytest

@pytest.fixture(scope="session")
def mock_site_server():
    from tests.benchmark.mock_site.server import MockSiteServer
    root = Path(__file__).parent / "mock_site"
    server = MockSiteServer(root_dir=root, port=0)
    server.start()
    yield server
    server.stop()

@pytest.fixture(scope="session")
def benchmark_base_url(mock_site_server) -> str:
    return f"http://localhost:{mock_site_server.port}"

@pytest.fixture(scope="session")
def benchmark_runner(benchmark_base_url):
    from tests.benchmark.runner import BenchmarkRunner
    return BenchmarkRunner(base_url=benchmark_base_url)
```

- [ ] **Step 2: Create test_benchmark.py**

```python
# tests/benchmark/test_benchmark.py
"""Benchmark test entry point — runs each scenario as a parametrized test case.

Usage:
    pytest tests/benchmark/test_benchmark.py -m benchmark -v
    pytest tests/benchmark/test_benchmark.py -m benchmark -k "products" -v
"""
from __future__ import annotations
from pathlib import Path
import pytest

SCENARIOS = ["products", "categories", "dynamic", "variants", "nested"]

@pytest.mark.benchmark
@pytest.mark.parametrize("scenario_id", SCENARIOS)
def test_scenario(scenario_id: str, benchmark_runner, benchmark_base_url, tmp_path: Path):
    from tests.benchmark.scenarios.schema import load_scenario
    config = load_scenario(scenario_id)
    try:
        from autospider.cli_runtime import build_doctor_sections
    except ImportError:
        pytest.skip("AutoSpider runtime not available")
    result = benchmark_runner.run_scenario(scenario_id)
    eval_result = result.evaluation_result
    assert eval_result.record_metrics.recall >= config.evaluation.thresholds.min_record_recall
    assert eval_result.overall_field_f1 >= config.evaluation.thresholds.min_field_f1
```

- [ ] **Step 3: Add CLI benchmark command** to `src/autospider/cli.py`

Add `@app.command("benchmark")` with options: `--all`, `--scenario/-s`, `--list`, `--report`, `--compare-last`. The command starts mock server, runs BenchmarkRunner, displays Rich table, generates JSON+MD reports.

- [ ] **Step 4: Update .gitignore** — append `tests/benchmark/reports/`

- [ ] **Step 5: Write integration test**

```python
# tests/benchmark/test_cli_benchmark.py
def test_benchmark_command_registered():
    from autospider.cli import app
    command_names = [cmd.name for cmd in app.registered_commands]
    assert "benchmark" in command_names
```

- [ ] **Step 6: Run tests**

```bash
pytest tests/benchmark/ -v --ignore=tests/benchmark/test_benchmark.py
```

- [ ] **Step 7: Commit**

```bash
git add tests/benchmark/conftest.py tests/benchmark/test_benchmark.py tests/benchmark/test_cli_benchmark.py src/autospider/cli.py .gitignore
git commit -m "feat(benchmark): add pytest conftest, test entry, and CLI benchmark command"
```

---

## 计划完成 ✅

### 任务总览

| Task | 内容 | 文件数 |
|------|------|--------|
| 1 | 场景 YAML Schema + 加载器 | 4 |
| 2 | 模拟网站静态文件服务器 | 3 |
| 3 | 指标计算引擎 | 2 |
| 4 | 评估引擎 | 2 |
| 5 | 模拟网站共享资源 + Products 页面 | ~22 |
| 6 | Products 场景 YAML + Ground Truth | 3 |
| 7 | 其余 4 场景页面生成脚本 | ~50 |
| 8 | 其余 4 场景 YAML + Ground Truth | 9 |
| 9 | 报告生成器 | 2 |
| 10 | 基准测试运行器 | 2 |
| 11 | pytest conftest + CLI 集成 | 5 |

### 执行顺序约束

Task 1~4 可并行（无依赖）。Task 5~6 依赖 Task 1+2。Task 7~8 依赖 Task 2。Task 9 依赖 Task 4。Task 10 依赖 Task 1+4+9。Task 11 依赖 Task 2+10。
