"""Pytest fixtures for benchmark scenario tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.benchmark.mock_site.server import MockSiteServer
from tests.benchmark.runner import BenchmarkRunner

BENCHMARK_DIR = Path(__file__).resolve().parent
MOCK_SITE_ROOT = BENCHMARK_DIR / "mock_site"
SCENARIOS_DIR = BENCHMARK_DIR / "scenarios"
GROUND_TRUTH_DIR = BENCHMARK_DIR / "ground_truth"


@pytest.fixture(scope="session")
def mock_site_server() -> MockSiteServer:
    """Start one mock site server per pytest session."""
    server = MockSiteServer(root_dir=MOCK_SITE_ROOT, port=0)
    server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture(scope="session")
def benchmark_base_url(mock_site_server: MockSiteServer) -> str:
    """Provide the mock benchmark site base URL."""
    return f"http://127.0.0.1:{mock_site_server.port}"


@pytest.fixture(scope="session")
def benchmark_runner(benchmark_base_url: str) -> BenchmarkRunner:
    """Create a benchmark runner bound to the benchmark test assets."""
    return BenchmarkRunner(
        scenarios_dir=SCENARIOS_DIR,
        ground_truth_dir=GROUND_TRUTH_DIR,
        base_url=benchmark_base_url,
    )
