from __future__ import annotations

import shutil
import sys
import tempfile
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = REPO_ROOT / "tests"
WORKSPACE_PREFIX = "autospider-e2e-runtime-"


def _ensure_local_tests_package() -> None:
    tests_module = sys.modules.get("tests")
    expected_path = str(TESTS_ROOT)
    current_paths = [str(path) for path in getattr(tests_module, "__path__", [])]
    if expected_path in current_paths:
        return
    local_tests = types.ModuleType("tests")
    local_tests.__path__ = [expected_path]
    sys.modules["tests"] = local_tests


_ensure_local_tests_package()

from tests.e2e.cases import CASE_BY_ID
from tests.e2e.env import (
    E2ERuntime,
    build_case_output_dir,
    prepare_e2e_runtime,
    reset_e2e_state,
    teardown_e2e_runtime,
)

_SESSION_RUNTIME: E2ERuntime | None = None
_SESSION_RUNTIME_SKIP_REASON: str | None = None


def _ensure_src_path() -> None:
    src_root = REPO_ROOT / "src"
    src_text = str(src_root)
    if src_text not in sys.path:
        sys.path.insert(0, src_text)


_ensure_src_path()


def _session_workspace_root() -> Path:
    return REPO_ROOT / ".tmp" / "e2e-runtime"


def _workspace_roots() -> tuple[Path, ...]:
    return (
        _session_workspace_root(),
        REPO_ROOT / "artifacts" / "test_tmp" / "e2e-runtime",
    )


def _create_workspace(base_dir: Path) -> Path:
    base_dir.mkdir(parents=True, exist_ok=True)
    workspace = tempfile.mkdtemp(prefix=WORKSPACE_PREFIX, dir=base_dir)
    return Path(workspace)


def _initialize_session_runtime(workspace_root: Path | None = None) -> tuple[E2ERuntime | None, str | None]:
    roots = (workspace_root,) if workspace_root is not None else _workspace_roots()
    last_error: Exception | None = None
    for base_dir in roots:
        workspace: Path | None = None
        try:
            workspace = _create_workspace(base_dir)
            return prepare_e2e_runtime(workspace), None
        except (RuntimeError, PermissionError, OSError, ModuleNotFoundError) as exc:
            last_error = exc
            if workspace is not None:
                shutil.rmtree(workspace, ignore_errors=True)
    if last_error is None:
        return None, "E2E 基础设施不可用: 未找到可写工作目录。"
    return None, f"E2E 基础设施不可用: {last_error}"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "e2e: end-to-end graph tests")
    global _SESSION_RUNTIME, _SESSION_RUNTIME_SKIP_REASON
    if _SESSION_RUNTIME is not None or _SESSION_RUNTIME_SKIP_REASON is not None:
        return
    _SESSION_RUNTIME, _SESSION_RUNTIME_SKIP_REASON = _initialize_session_runtime()


def pytest_unconfigure(config: pytest.Config) -> None:
    del config
    global _SESSION_RUNTIME, _SESSION_RUNTIME_SKIP_REASON
    if _SESSION_RUNTIME is None:
        _SESSION_RUNTIME_SKIP_REASON = None
        return
    teardown_e2e_runtime(_SESSION_RUNTIME)
    _SESSION_RUNTIME = None
    _SESSION_RUNTIME_SKIP_REASON = None


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    del config
    e2e_root = Path(__file__).resolve().parent
    for item in items:
        if Path(str(item.fspath)).resolve().is_relative_to(e2e_root):
            item.add_marker(pytest.mark.e2e)
            if _SESSION_RUNTIME_SKIP_REASON is None:
                continue
            skip_marker = pytest.mark.skip(reason=_SESSION_RUNTIME_SKIP_REASON)
            item.add_marker(skip_marker)


@pytest.fixture(scope="session")
def e2e_runtime() -> E2ERuntime:
    if _SESSION_RUNTIME is None:
        reason = _SESSION_RUNTIME_SKIP_REASON or "E2E runtime 尚未初始化。"
        pytest.skip(reason)
    return _SESSION_RUNTIME


@pytest.fixture(scope="session")
def e2e_environment(e2e_runtime: E2ERuntime) -> E2ERuntime:
    return e2e_runtime


@pytest.fixture(scope="session")
def e2e_root() -> Path:
    return Path(__file__).parent


@pytest.fixture(scope="session")
def e2e_output_root(e2e_runtime: E2ERuntime) -> Path:
    return e2e_runtime.output_root


@pytest.fixture(scope="session")
def mock_site():
    from tests.e2e.mock_site import MockSiteServer

    server = MockSiteServer().start()
    yield server
    server.stop()


@pytest.fixture(scope="session")
def mock_site_base_url(mock_site) -> str:
    return str(mock_site.base_url).rstrip("/")


@pytest.fixture(scope="session")
def graph_e2e_cases():
    return CASE_BY_ID


@pytest.fixture()
def graph_e2e_driver():
    from tests.e2e.harness import GraphRunnerE2EHarness

    return GraphRunnerE2EHarness()


def _is_sqlalchemy_infra_error(exc: Exception) -> bool:
    try:
        from sqlalchemy.exc import SQLAlchemyError
    except ModuleNotFoundError:
        return False
    return isinstance(exc, SQLAlchemyError)


def _reset_or_skip_e2e_state() -> None:
    try:
        reset_e2e_state()
    except (ModuleNotFoundError, OSError, RuntimeError) as exc:
        pytest.skip(f"E2E 基础设施不可用: {exc}")
    except Exception as exc:
        if _is_sqlalchemy_infra_error(exc):
            pytest.skip(f"E2E 基础设施不可用: {exc}")
        raise


@pytest.fixture(autouse=True)
def e2e_case_state(e2e_runtime: E2ERuntime):
    del e2e_runtime
    _reset_or_skip_e2e_state()
    yield
    _reset_or_skip_e2e_state()


@pytest.fixture()
def e2e_case_output_dir(
    e2e_output_root: Path,
    request: pytest.FixtureRequest,
) -> Path:
    return build_case_output_dir(output_root=e2e_output_root, node_id=request.node.nodeid)


@pytest.fixture()
def e2e_output_dir(e2e_case_output_dir: Path) -> Path:
    return e2e_case_output_dir
