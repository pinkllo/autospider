from __future__ import annotations

import importlib
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class BenchmarkPaths:
    benchmark: Path
    scenarios: Path
    ground_truth: Path
    mock_site: Path


class BenchmarkReportService:
    def __init__(self, repo_root: Path | None = None) -> None:
        self._repo_root = repo_root or Path(__file__).resolve().parents[4]

    def benchmark_paths(self) -> BenchmarkPaths:
        root = self._repo_root / "tests" / "benchmark"
        return BenchmarkPaths(
            benchmark=root,
            scenarios=root / "scenarios",
            ground_truth=root / "ground_truth",
            mock_site=root / "mock_site",
        )

    def reports_dir(self) -> Path:
        return self._repo_root / "output" / "benchmark" / "reports"

    def json_reports(self) -> list[Path]:
        return sorted(self.reports_dir().glob("*.json"))

    def latest_report_path(self) -> Path:
        reports = self.json_reports()
        if not reports:
            raise FileNotFoundError(f"No benchmark reports found in {self.reports_dir()}")
        return reports[-1]

    def last_two_report_paths(self) -> tuple[Path, Path]:
        reports = self.json_reports()
        if len(reports) < 2:
            raise FileNotFoundError(f"Need at least two benchmark reports in {self.reports_dir()}")
        return reports[-2], reports[-1]

    def benchmark_git_commit(self) -> str:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            check=False,
            cwd=self._repo_root,
            text=True,
        )
        return result.stdout.strip() or "unknown"

    def report_stem(self) -> str:
        return f"benchmark_{int(time.time())}_{threading.get_native_id()}"

    def load_runner_class(self) -> type:
        return getattr(importlib.import_module("tests.benchmark.runner"), "BenchmarkRunner")

    def load_reporter(self) -> Any:
        return importlib.import_module("tests.benchmark.reporter")

    def list_scenarios(self) -> list[str]:
        schema_module = importlib.import_module("tests.benchmark.scenarios.schema")
        list_scenarios = getattr(schema_module, "list_scenarios")
        return list_scenarios(self.benchmark_paths().scenarios)
