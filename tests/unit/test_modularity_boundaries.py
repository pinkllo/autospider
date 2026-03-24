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


def test_common_types_planning_models_are_compat_exports():
    from autospider.common.types import SubTask as CompatSubTask
    from autospider.common.types import TaskPlan as CompatTaskPlan
    from autospider.domain.planning import SubTask, TaskPlan

    assert CompatSubTask is SubTask
    assert CompatTaskPlan is TaskPlan


def test_browser_test_uses_canonical_browser_entry():
    source = (PROJECT_ROOT / "tests" / "unit" / "test_browser_engine.py").read_text(
        encoding="utf-8"
    )

    assert "from autospider.common.browser.engine import (" in source
    assert "from common.browser_manager.engine import (" not in source


def test_browser_session_no_longer_mutates_sys_path_for_common_browser_manager():
    source = (PROJECT_ROOT / "src" / "autospider" / "common" / "browser" / "session.py").read_text(
        encoding="utf-8"
    )

    assert "sys.path.insert" not in source
    assert "from .engine import BrowserEngine, get_browser_engine, shutdown_browser_engine" in source


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


def test_external_common_python_sources_are_removed():
    common_root = PROJECT_ROOT / "src" / "common"
    assert list(common_root.rglob("*.py")) == []
