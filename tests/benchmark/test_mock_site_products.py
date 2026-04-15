"""Tests for benchmark mock site products pages."""

from __future__ import annotations

import re
import urllib.request
from pathlib import Path

import pytest

from tests.benchmark.mock_site.server import MockSiteServer

DETAIL_LINK_PATTERN = re.compile(r'href="(detail_\d+\.html)"')
FIELD_NAMES = ("product_name", "price", "brand", "specs", "product_url")
PRODUCT_PAGES = ("index.html", "page_2.html", "page_3.html")
PRODUCT_COUNT_PER_PAGE = 5
TOTAL_PRODUCT_COUNT = 15


@pytest.fixture()
def products_site_server() -> MockSiteServer:
    """Serve the real benchmark mock site root for products assets."""
    root_dir = Path(__file__).parent / "mock_site"
    server = MockSiteServer(root_dir=root_dir, port=0)
    server.start()
    try:
        yield server
    finally:
        server.stop()


def test_shared_assets_are_accessible(products_site_server: MockSiteServer) -> None:
    """Shared assets are served from /shared."""
    base_url = f"http://127.0.0.1:{products_site_server.port}"

    style_text = _read_text(f"{base_url}/shared/style.css")
    script_text = _read_text(f"{base_url}/shared/pagination.js")

    assert ":root" in style_text
    assert "pagination" in script_text.lower()


def test_products_listing_pages_expose_15_detail_links(
    products_site_server: MockSiteServer,
) -> None:
    """Products pagination exposes 3 pages with 5 detail links each."""
    base_url = f"http://127.0.0.1:{products_site_server.port}"
    all_links: set[str] = set()

    for page_name in PRODUCT_PAGES:
        page_html = _read_text(f"{base_url}/scenarios/products/{page_name}")
        page_links = DETAIL_LINK_PATTERN.findall(page_html)
        assert len(page_links) == PRODUCT_COUNT_PER_PAGE
        all_links.update(page_links)

    assert len(all_links) == TOTAL_PRODUCT_COUNT


def test_products_detail_pages_have_required_fields(
    products_site_server: MockSiteServer,
) -> None:
    """All 15 detail pages expose the core fields for future ground truth."""
    base_url = f"http://127.0.0.1:{products_site_server.port}"

    for index in range(1, TOTAL_PRODUCT_COUNT + 1):
        url = f"{base_url}/scenarios/products/detail_{index}.html"
        detail_html = _read_text(url)
        for field_name in FIELD_NAMES:
            assert f'data-field="{field_name}"' in detail_html
        assert f'href="/scenarios/products/detail_{index}.html"' in detail_html


def _read_text(url: str) -> str:
    with urllib.request.urlopen(url) as response:
        assert response.status == 200
        return response.read().decode("utf-8")
