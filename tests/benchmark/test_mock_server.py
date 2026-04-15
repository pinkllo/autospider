"""Tests for the benchmark mock static server."""

from __future__ import annotations

import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

import pytest


def test_server_starts_and_serves_files() -> None:
    """Server serves files from the configured mock site root."""
    from tests.benchmark.mock_site.server import MockSiteServer

    sample_site = _make_mock_site_root()
    server = MockSiteServer(root_dir=sample_site, port=0)

    server.start()
    try:
        base = f"http://127.0.0.1:{server.port}"
        assert _read_text(f"{base}/scenarios/products/index.html") == "Hello"
        assert _read_text(f"{base}/shared/style.css") == "body {}"
    finally:
        server.stop()


def test_server_returns_404_for_missing_file() -> None:
    """Missing files surface as HTTP 404."""
    from tests.benchmark.mock_site.server import MockSiteServer

    sample_site = _make_mock_site_root()
    server = MockSiteServer(root_dir=sample_site, port=0)

    server.start()
    try:
        base = f"http://127.0.0.1:{server.port}"
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(f"{base}/scenarios/products/missing.html")
        assert exc_info.value.code == 404
    finally:
        server.stop()


def test_default_root_dir_points_to_mock_site_package() -> None:
    """Default root directory keeps /scenarios and /shared under one root."""
    from tests.benchmark.mock_site.server import MockSiteServer

    server = MockSiteServer(port=0)

    assert server.root_dir.name == "mock_site"
    assert server.root_dir.joinpath("scenarios").parent == server.root_dir
    assert server.root_dir.joinpath("shared").parent == server.root_dir


def test_port_requires_started_server() -> None:
    """Port access before start is explicit."""
    from tests.benchmark.mock_site.server import MockSiteServer

    server = MockSiteServer(root_dir=_make_mock_site_root(), port=0)

    with pytest.raises(RuntimeError):
        _ = server.port


def _make_mock_site_root() -> Path:
    root = Path(".tmp") / "benchmark_tests" / "mock_site" / uuid4().hex
    scenarios_dir = root / "scenarios" / "products"
    shared_dir = root / "shared"
    scenarios_dir.mkdir(parents=True, exist_ok=False)
    shared_dir.mkdir(parents=True, exist_ok=False)
    (scenarios_dir / "index.html").write_text("Hello", encoding="utf-8")
    (shared_dir / "style.css").write_text("body {}", encoding="utf-8")
    return root


def _read_text(url: str) -> str:
    with urllib.request.urlopen(url) as response:
        return response.read().decode("utf-8")
