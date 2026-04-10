from __future__ import annotations

import importlib
import inspect
import json
import sys
from pathlib import Path
from typing import Any, Iterable

import pytest
from _pytest.fixtures import FixtureLookupError

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autospider.graph.types import GraphResult
from tests.e2e.contracts import (
    BASE_URL_PLACEHOLDER,
    BUSINESS_FIELDS,
    SUMMARY_FIELDS,
    GraphE2ECase,
    resolve_golden_path,
)

CASE_IDS = (
    "graph_all_categories",
    "graph_same_page_variant",
    "graph_direct_list_pagination_dedupe",
)
CASE_FIXTURE_NAMES = ("graph_e2e_cases", "e2e_cases", "cases_by_id")
DRIVER_FIXTURE_NAMES = ("graph_e2e_driver", "graph_harness", "e2e_harness")
BASE_URL_FIXTURE_NAMES = ("mock_site_base_url", "base_url", "mock_site_url", "mock_site_server")
CASE_MODULE_CANDIDATES = (
    "tests.e2e.cases",
    "tests.e2e.cases.registry",
    "tests.e2e.cases.manifests",
)


def _resolve_fixture(request: pytest.FixtureRequest, names: Iterable[str]) -> Any:
    for name in names:
        try:
            return request.getfixturevalue(name)
        except FixtureLookupError:
            continue
    joined = ", ".join(names)
    raise AssertionError(f"缺少测试所需 fixture，尝试过: {joined}")


def _coerce_cases(raw_cases: Any) -> dict[str, GraphE2ECase]:
    if isinstance(raw_cases, dict):
        values = raw_cases.values()
    elif isinstance(raw_cases, (list, tuple)):
        values = raw_cases
    else:
        raise TypeError(f"无法识别的 case 容器类型: {type(raw_cases)!r}")

    registry: dict[str, GraphE2ECase] = {}
    for item in values:
        if not isinstance(item, GraphE2ECase):
            raise TypeError(f"case 必须是 GraphE2ECase，实际是: {type(item)!r}")
        registry[item.case_id] = item
    return registry


def _load_cases_from_module() -> dict[str, GraphE2ECase] | None:
    for module_name in CASE_MODULE_CANDIDATES:
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError:
            continue
        for attr_name in ("CASE_BY_ID", "ALL_CASES", "CASES", "GRAPH_E2E_CASES", "cases", "graph_e2e_cases"):
            if hasattr(module, attr_name):
                return _coerce_cases(getattr(module, attr_name))
    return None


def _resolve_cases(request: pytest.FixtureRequest) -> dict[str, GraphE2ECase]:
    for fixture_name in CASE_FIXTURE_NAMES:
        try:
            return _coerce_cases(request.getfixturevalue(fixture_name))
        except FixtureLookupError:
            continue
    cases = _load_cases_from_module()
    if cases is None:
        joined = ", ".join(CASE_FIXTURE_NAMES)
        raise AssertionError(f"未找到 case 注册表 fixture 或模块，尝试过: {joined}")
    return cases


def _resolve_case(request: pytest.FixtureRequest, case_id: str) -> GraphE2ECase:
    cases = _resolve_cases(request)
    if case_id not in cases:
        available = ", ".join(sorted(cases))
        raise AssertionError(f"缺少 case={case_id}，当前可用: {available}")
    return cases[case_id]


def _resolve_base_url(request: pytest.FixtureRequest) -> str:
    raw = _resolve_fixture(request, BASE_URL_FIXTURE_NAMES)
    if isinstance(raw, str):
        return raw.rstrip("/")
    if isinstance(raw, dict) and raw.get("base_url"):
        return str(raw["base_url"]).rstrip("/")
    base_url = getattr(raw, "base_url", "")
    if base_url:
        return str(base_url).rstrip("/")
    raise TypeError(f"无法从 mock site fixture 解析 base_url: {type(raw)!r}")


def _coerce_graph_result(run_output: Any) -> GraphResult:
    payload = run_output
    if isinstance(payload, GraphResult):
        return payload
    if isinstance(payload, dict) and "graph_result" in payload:
        payload = payload["graph_result"]
    elif hasattr(payload, "graph_result"):
        payload = getattr(payload, "graph_result")
    if isinstance(payload, GraphResult):
        return payload
    return GraphResult.model_validate(payload)


def _artifact_path_from_bundle(bundle: Any, label: str) -> Path | None:
    output_files = getattr(bundle, "output_files", None)
    if output_files is not None:
        if label == "merged_results" and getattr(output_files, "merged_results_path", None):
            return Path(str(output_files.merged_results_path))
        if label == "merged_summary" and getattr(output_files, "merged_summary_path", None):
            return Path(str(output_files.merged_summary_path))
    if not isinstance(bundle, dict):
        return None
    direct_keys = (
        f"{label}_path",
        f"{label}_file",
        label,
    )
    for key in direct_keys:
        value = bundle.get(key)
        if value:
            return Path(str(value))
    return None


def _resolve_artifact_path(graph_result: GraphResult, *, label: str, run_output: Any) -> Path:
    bundle_path = _artifact_path_from_bundle(run_output, label)
    if bundle_path is not None:
        return bundle_path
    for item in graph_result.artifacts:
        if str(item.get("label") or "") == label:
            return Path(str(item.get("path") or ""))
    raise AssertionError(f"未找到产物 {label}，当前 artifacts={graph_result.artifacts}")


def _normalize_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in records:
        normalized.append({field: item.get(field) for field in BUSINESS_FIELDS})
    return sorted(normalized, key=lambda row: tuple(str(row.get(field) or "") for field in BUSINESS_FIELDS))


def _normalize_summary(summary: dict[str, Any]) -> dict[str, int]:
    return {field: int(summary.get(field) or 0) for field in SUMMARY_FIELDS}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped:
            rows.append(json.loads(stripped))
    return rows


def _load_records(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        return _load_jsonl(path)
    payload = _load_json(path)
    if not isinstance(payload, list):
        raise TypeError(f"golden records 必须是列表: {path}")
    return payload


def _materialize_expected_records(records: list[dict[str, Any]], *, base_url: str) -> list[dict[str, Any]]:
    normalized_base_url = base_url.rstrip("/")
    rendered: list[dict[str, Any]] = []
    for row in records:
        rendered.append({
            str(key): (
                str(value).replace(BASE_URL_PLACEHOLDER, normalized_base_url)
                if isinstance(value, str)
                else value
            )
            for key, value in row.items()
        })
    return rendered


async def _invoke_driver(
    driver: Any,
    *,
    case: GraphE2ECase,
    base_url: str,
    output_dir: Path,
) -> Any:
    candidates: list[Any] = []
    if callable(driver):
        candidates.append(driver)
    for name in ("run_case", "execute_case", "run"):
        method = getattr(driver, name, None)
        if method is not None:
            candidates.append(method)
    if not candidates:
        raise TypeError(f"harness 不可调用: {type(driver)!r}")

    call_kwargs = {
        "case": case,
        "case_id": case.case_id,
        "base_url": base_url,
        "request_text": case.materialize_request_text(base_url=base_url),
        "override_task": case.materialize_override_task(base_url=base_url),
        "clarification_answers": case.materialize_answers(base_url=base_url),
        "output_dir": output_dir,
    }
    for candidate in candidates:
        signature = inspect.signature(candidate)
        supported_kwargs = {key: value for key, value in call_kwargs.items() if key in signature.parameters}
        result = candidate(**supported_kwargs)
        if inspect.isawaitable(result):
            return await result
        return result
    raise AssertionError("未能调用 graph harness")


def _format_failure(graph_result: GraphResult) -> str:
    return (
        f"status={graph_result.status}, "
        f"error={graph_result.error}, "
        f"interrupts={graph_result.interrupts}, "
        f"summary={graph_result.summary}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("case_id", CASE_IDS, ids=CASE_IDS)
async def test_graph_e2e(case_id: str, request: pytest.FixtureRequest) -> None:
    base_url = _resolve_base_url(request)
    case = _resolve_case(request, case_id)
    driver = _resolve_fixture(request, DRIVER_FIXTURE_NAMES)
    output_dir = request.getfixturevalue("e2e_output_dir")

    run_output = await _invoke_driver(
        driver,
        case=case,
        base_url=base_url,
        output_dir=output_dir,
    )
    graph_result = _coerce_graph_result(run_output)

    assert graph_result.status == "success", _format_failure(graph_result)

    merged_results_path = _resolve_artifact_path(graph_result, label="merged_results", run_output=run_output)
    merged_summary_path = _resolve_artifact_path(graph_result, label="merged_summary", run_output=run_output)
    assert merged_results_path.exists(), f"缺少 merged_results 文件: {merged_results_path}"
    assert merged_summary_path.exists(), f"缺少 merged_summary 文件: {merged_summary_path}"

    expected_records_path = resolve_golden_path(root=Path(__file__).resolve().parent, case=case)
    assert expected_records_path.exists(), f"缺少 golden records 文件: {expected_records_path}"

    actual_records = _normalize_records(_load_records(merged_results_path))
    expected_records = _normalize_records(
        _materialize_expected_records(_load_records(expected_records_path), base_url=base_url)
    )
    actual_summary = _normalize_summary(_load_json(merged_summary_path))
    expected_summary = _normalize_summary(case.materialize_expected_summary(base_url=base_url))

    assert actual_records == expected_records
    assert actual_summary == expected_summary
