from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

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
    src_root = Path(__file__).resolve().parents[2] / "src"
    src_text = str(src_root)
    if src_text not in sys.path:
        sys.path.insert(0, src_text)


_ensure_src_path()


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "e2e: end-to-end graph tests")
    global _SESSION_RUNTIME, _SESSION_RUNTIME_SKIP_REASON
    if _SESSION_RUNTIME is not None or _SESSION_RUNTIME_SKIP_REASON is not None:
        return
    workspace = Path(tempfile.mkdtemp(prefix="autospider-e2e-runtime-"))
    try:
        _SESSION_RUNTIME = prepare_e2e_runtime(workspace)
    except RuntimeError as exc:
        _SESSION_RUNTIME_SKIP_REASON = f"E2E 基础设施不可用: {exc}"


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
    if _SESSION_RUNTIME_SKIP_REASON is None:
        return
    skip_marker = pytest.mark.skip(reason=_SESSION_RUNTIME_SKIP_REASON)
    e2e_root = Path(__file__).resolve().parent
    for item in items:
        if Path(str(item.fspath)).resolve().is_relative_to(e2e_root):
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


@pytest.fixture(autouse=True)
def e2e_case_state(e2e_runtime: E2ERuntime):
    del e2e_runtime
    reset_e2e_state()
    yield
    reset_e2e_state()


@pytest.fixture()
def e2e_case_output_dir(
    e2e_output_root: Path,
    request: pytest.FixtureRequest,
) -> Path:
    return build_case_output_dir(output_root=e2e_output_root, node_id=request.node.nodeid)


@pytest.fixture()
def e2e_output_dir(e2e_case_output_dir: Path) -> Path:
    return e2e_case_output_dir
