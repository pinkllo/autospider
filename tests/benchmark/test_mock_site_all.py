"""Tests for benchmark mock site scenarios beyond products."""

from __future__ import annotations

import urllib.request
from pathlib import Path

import pytest

from tests.benchmark.mock_site.server import MockSiteServer

CATEGORIES_DETAIL_COUNT = 15
DYNAMIC_DETAIL_COUNT = 9
VARIANTS_CARD_COUNT = 5
VARIANTS_TABLE_COUNT = 5
NESTED_LIST_COUNT = 4
NESTED_DETAIL_COUNT = 12


@pytest.fixture(scope="module")
def site_server() -> MockSiteServer:
    """Serve the benchmark mock site root for all extra scenarios."""
    root_dir = Path(__file__).parent / "mock_site"
    server = MockSiteServer(root_dir=root_dir, port=0)
    server.start()
    try:
        yield server
    finally:
        server.stop()


def test_shared_dynamic_assets_are_accessible(site_server: MockSiteServer) -> None:
    """Shared JS assets for dynamic and tab behavior are served."""
    base_url = _base_url(site_server)

    tabs_script = _read_text(f"{base_url}/shared/tabs.js")
    dynamic_script = _read_text(f"{base_url}/shared/dynamic_load.js")

    assert "tab" in tabs_script.lower()
    assert "load" in dynamic_script.lower()


def test_categories_pages(site_server: MockSiteServer) -> None:
    """Categories index and all detail pages exist with tab navigation markers."""
    base_url = _base_url(site_server)
    index_html = _read_text(f"{base_url}/scenarios/categories/index.html")

    assert "tab-nav" in index_html
    for label in ("Phones", "Computers", "Accessories"):
        assert label in index_html
    for index in range(1, CATEGORIES_DETAIL_COUNT + 1):
        _read_text(f"{base_url}/scenarios/categories/detail_{index}.html")


def test_dynamic_pages(site_server: MockSiteServer) -> None:
    """Dynamic scenario exposes load-more and collapsible detail content."""
    base_url = _base_url(site_server)
    index_html = _read_text(f"{base_url}/scenarios/dynamic/index.html")
    detail_html = _read_text(f"{base_url}/scenarios/dynamic/detail_1.html")

    assert "load-more-btn" in index_html
    assert "collapsible" in detail_html
    for index in range(1, DYNAMIC_DETAIL_COUNT + 1):
        _read_text(f"{base_url}/scenarios/dynamic/detail_{index}.html")


def test_variants_pages(site_server: MockSiteServer) -> None:
    """Variants scenario exposes both card and table detail layouts."""
    base_url = _base_url(site_server)
    index_html = _read_text(f"{base_url}/scenarios/variants/index.html")

    assert "card_" in index_html
    assert "table_" in index_html
    for index in range(1, VARIANTS_CARD_COUNT + 1):
        _read_text(f"{base_url}/scenarios/variants/card_{index}.html")
    for index in range(1, VARIANTS_TABLE_COUNT + 1):
        _read_text(f"{base_url}/scenarios/variants/table_{index}.html")


def test_nested_pages(site_server: MockSiteServer) -> None:
    """Nested scenario exposes tree navigation, leaf lists, and all details."""
    base_url = _base_url(site_server)
    index_html = _read_text(f"{base_url}/scenarios/nested/index.html")

    assert "tree-nav" in index_html
    for index in range(1, NESTED_LIST_COUNT + 1):
        _read_text(f"{base_url}/scenarios/nested/list_{index}.html")
    for index in range(1, NESTED_DETAIL_COUNT + 1):
        _read_text(f"{base_url}/scenarios/nested/detail_{index}.html")


def _base_url(site_server: MockSiteServer) -> str:
    return f"http://127.0.0.1:{site_server.port}"


def _read_text(url: str) -> str:
    with urllib.request.urlopen(url) as response:
        assert response.status == 200
        return response.read().decode("utf-8")
