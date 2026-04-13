from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = REPO_ROOT / "tests"
tests_root_text = str(TESTS_ROOT)
if tests_root_text not in sys.path:
    sys.path.insert(0, tests_root_text)
local_tests_package = types.ModuleType("tests")
local_tests_package.__path__ = [tests_root_text]
sys.modules["tests"] = local_tests_package

from tests.e2e import conftest as e2e_conftest
from tests.e2e import test_graph_e2e as graph_e2e_module
from tests.e2e.env import runtime as runtime_module
from tests.e2e.mock_site.pages import render_home_page


pytestmark = pytest.mark.smoke

README_FILES = (
    REPO_ROOT / "README.md",
    REPO_ROOT / "README_en.md",
    REPO_ROOT / "tests" / "e2e" / "README.md",
)


def test_e2e_runtime_env_updates_use_redis_pipeline_mode() -> None:
    env_updates = runtime_module._build_env_updates(
        database_url="postgresql://example",
        redis_url="redis://127.0.0.1:6379/15",
        output_root=Path("d:/autospider/.tmp/e2e-runtime"),
    )

    assert env_updates["PIPELINE_MODE"] == "redis"


def test_initialize_session_runtime_converts_permission_error_to_skip_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _deny(_workspace: Path):
        raise PermissionError("denied")

    monkeypatch.setattr(e2e_conftest, "prepare_e2e_runtime", _deny)

    runtime_root = REPO_ROOT / ".tmp" / "smoke-runtime-init"
    runtime, skip_reason = e2e_conftest._initialize_session_runtime(runtime_root)

    assert runtime is None
    assert skip_reason is not None
    assert "E2E 基础设施不可用" in skip_reason
    assert "denied" in skip_reason


def test_graph_e2e_module_declares_e2e_marker() -> None:
    markers = getattr(graph_e2e_module, "pytestmark", [])
    if not isinstance(markers, list):
        markers = [markers]

    assert any(getattr(marker, "name", "") == "e2e" for marker in markers)


def test_same_page_variant_home_page_contains_decoy_before_real_tab() -> None:
    html = render_home_page(base_url="https://mock.local")

    assert 'id="deals-tab-decoy"' in html
    assert html.index('id="deals-tab-decoy"') < html.index('id="deals-tab"')
    assert "document.getElementById('deals-tab').click();" not in html


def test_same_page_variant_contract_accepts_deal_only_urls() -> None:
    graph_e2e_module._assert_same_page_variant_records(
        records=[
            {
                "url": "https://mock.local/details/deal/deal-001",
                "title": "成交结果公告",
                "publish_date": "2026-01-01",
                "budget": "100",
                "attachment_url": "https://mock.local/downloads/deal/deal-001.pdf",
            }
        ],
        base_url="https://mock.local",
    )


@pytest.mark.parametrize("readme_path", README_FILES, ids=lambda path: path.name)
def test_readmes_match_current_developer_entrypoints(readme_path: Path) -> None:
    content = readme_path.read_text(encoding="utf-8")

    assert "autospider doctor" in content
    assert "pytest tests/e2e -m e2e -q" in content
    assert "application/" not in content
