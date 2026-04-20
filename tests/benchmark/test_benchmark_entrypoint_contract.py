"""Contract tests for benchmark pytest fixtures."""

from __future__ import annotations


def test_benchmark_runner_fixture_has_expected_api(benchmark_runner: object) -> None:
    """benchmark_runner exposes list and run operations."""
    assert hasattr(benchmark_runner, "list_scenarios")
    assert hasattr(benchmark_runner, "run_scenario")


def test_mock_site_server_fixture_exposes_port(mock_site_server: object) -> None:
    """mock_site_server exposes a started server with a usable port."""
    assert hasattr(mock_site_server, "port")
    assert isinstance(mock_site_server.port, int)
    assert mock_site_server.port > 0
