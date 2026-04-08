from __future__ import annotations

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def test_task_clarifier_no_longer_depends_on_field_package():
    source = (PROJECT_ROOT / "src" / "autospider" / "common" / "llm" / "task_clarifier.py").read_text(
        encoding="utf-8"
    )

    assert "from ...field import FieldDefinition" not in source
    assert "from ...domain.fields import FieldDefinition" in source


def test_legacy_prompt_template_is_a_shim_to_canonical_module():
    assert not (PROJECT_ROOT / "src" / "common" / "utils" / "prompt_template.py").exists()


def test_common_types_no_longer_exports_planning_models():
    source = (PROJECT_ROOT / "src" / "autospider" / "common" / "types.py").read_text(
        encoding="utf-8"
    )

    assert "from ..domain.planning import SubTask" not in source
    assert "from ..domain.planning import TaskPlan" not in source


def test_browser_test_uses_canonical_browser_entry():
    source = (PROJECT_ROOT / "tests" / "unit" / "test_browser_engine.py").read_text(
        encoding="utf-8"
    )

    assert "from autospider.common.browser.engine import (" in source
    assert "from common.browser_manager.engine import (" not in source


def test_browser_session_no_longer_mutates_sys_path_for_common_browser_manager():
    assert not (PROJECT_ROOT / "src" / "autospider" / "common" / "browser" / "session.py").exists()


def test_browser_intervention_is_canonical_and_legacy_module_is_a_shim():
    canonical_source = (
        PROJECT_ROOT / "src" / "autospider" / "common" / "browser" / "intervention.py"
    ).read_text(encoding="utf-8")

    assert "from common.browser_manager.intervention import" not in canonical_source
    assert not (PROJECT_ROOT / "src" / "common" / "browser_manager" / "intervention.py").exists()


def test_browser_engine_and_guarded_page_are_canonical_and_legacy_modules_are_shims():
    engine_source = (
        PROJECT_ROOT / "src" / "autospider" / "common" / "browser" / "engine.py"
    ).read_text(encoding="utf-8")
    guarded_page_source = (
        PROJECT_ROOT / "src" / "autospider" / "common" / "browser" / "guarded_page.py"
    ).read_text(encoding="utf-8")

    assert "from common.browser_manager.engine import" not in engine_source
    assert "from common.browser_manager.guarded_page import" not in guarded_page_source
    assert not (PROJECT_ROOT / "src" / "common" / "browser_manager" / "engine.py").exists()
    assert not (PROJECT_ROOT / "src" / "common" / "browser_manager" / "guarded_page.py").exists()


def test_persistence_uses_canonical_file_utils_entry():
    source = (PROJECT_ROOT / "src" / "autospider" / "common" / "storage" / "persistence.py").read_text(
        encoding="utf-8"
    )

    assert "sys.path.insert" not in source
    assert "from ..utils.file_utils import ensure_directory, file_exists, load_json" in source


def test_legacy_file_utils_is_a_shim_to_canonical_module():
    assert not (PROJECT_ROOT / "src" / "common" / "utils" / "file_utils.py").exists()


def test_legacy_async_file_utils_is_a_shim_to_canonical_module():
    assert not (PROJECT_ROOT / "src" / "common" / "utils" / "file_utils_async.py").exists()


def test_services_exports_and_aliases_are_trimmed_to_canonical_entries():
    source = (PROJECT_ROOT / "src" / "autospider" / "services" / "__init__.py").read_text(
        encoding="utf-8"
    )

    assert "TaskRunQueryService" not in source
    assert "CollectionService" not in source
    assert "FieldService" not in source
    assert "PlanningService" not in source
    assert "AggregationService" not in source
    assert "compatibility" not in source.lower()
    assert "PlanMutationService" in source
    assert "RuntimeExpansionService" in source


def test_legacy_service_modules_are_removed():
    services_root = PROJECT_ROOT / "src" / "autospider" / "services"

    assert sorted(path.name for path in services_root.glob("*.py")) == [
        "__init__.py",
        "plan_mutation_service.py",
        "runtime_expansion_service.py",
    ]


def test_capability_nodes_no_longer_define_execute_facades():
    source = (
        PROJECT_ROOT / "src" / "autospider" / "graph" / "nodes" / "capability_nodes.py"
    ).read_text(encoding="utf-8")

    assert "async def execute_pipeline(" not in source
    assert "async def execute_url_collection(" not in source
    assert "async def execute_config_generation(" not in source
    assert "async def execute_batch_collection(" not in source
    assert "async def execute_field_extraction(" not in source
    assert "async def execute_planning(" not in source
    assert "async def execute_aggregation(" not in source


def test_capability_nodes_use_application_use_cases_on_main_path():
    source = (
        PROJECT_ROOT / "src" / "autospider" / "graph" / "nodes" / "capability_nodes.py"
    ).read_text(encoding="utf-8")

    assert "AggregateResultsUseCase" in source
    assert "CollectUrlsUseCase" in source
    assert "GenerateCollectionConfigUseCase" in source
    assert "BatchCollectUrlsUseCase" in source
    assert "ExtractFieldsUseCase" in source
    assert "ExecutePipelineUseCase" in source
    assert "PlanUseCase" in source
    assert "CollectionService" not in source
    assert "FieldService" not in source
    assert "PlanningService" not in source
    assert "AggregationService" not in source


def test_storage_query_services_are_used_on_main_path():
    entry_source = (
        PROJECT_ROOT / "src" / "autospider" / "graph" / "nodes" / "entry_nodes.py"
    ).read_text(encoding="utf-8")
    detail_worker_source = (
        PROJECT_ROOT / "src" / "autospider" / "field" / "detail_page_worker.py"
    ).read_text(encoding="utf-8")

    assert "TaskRunQueryService" in entry_source
    assert "TaskRegistry" not in entry_source
    assert "FieldXPathQueryService" in detail_worker_source
    assert "FieldXPathWriteService" in detail_worker_source


def test_legacy_storage_and_browser_modules_are_removed():
    assert not (PROJECT_ROOT / "src" / "autospider" / "common" / "storage" / "task_registry.py").exists()
    assert not (
        PROJECT_ROOT / "src" / "autospider" / "common" / "storage" / "field_xpath_registry.py"
    ).exists()
    assert not (PROJECT_ROOT / "src" / "autospider" / "common" / "browser" / "session.py").exists()


def test_task_run_query_service_module_is_removed():
    assert not (PROJECT_ROOT / "src" / "autospider" / "services" / "task_run_service.py").exists()


def test_external_common_python_sources_are_removed():
    common_root = PROJECT_ROOT / "src" / "common"
    assert list(common_root.rglob("*.py")) == []
