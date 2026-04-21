from __future__ import annotations

import importlib
import logging
import shutil
import sys
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.smoke

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def _detach_logger_handlers(logger_module) -> None:
    root_logger = logging.getLogger()
    for handler_name in ("_CONSOLE_HANDLER", "_FILE_HANDLER"):
        handler = getattr(logger_module, handler_name, None)
        if handler is None:
            continue
        root_logger.removeHandler(handler)
        handler.close()
        setattr(logger_module, handler_name, None)
    logger_module._CURRENT_LOG_FILE = ""
    logger_module._BOOTSTRAPPED = False


@pytest.fixture()
def repo_tmp_dir() -> Path:
    base_dir = REPO_ROOT / "artifacts" / "test_tmp"
    base_dir.mkdir(parents=True, exist_ok=True)
    path = base_dir / f"logger-tests-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture()
def load_logger_module():
    def _load():
        import autospider.platform.observability.logger as logger_module

        _detach_logger_handlers(logger_module)
        return importlib.reload(logger_module)

    yield _load

    import autospider.platform.observability.logger as logger_module

    _detach_logger_handlers(logger_module)


def test_get_logger_bootstraps_with_first_log_level(
    monkeypatch: pytest.MonkeyPatch,
    load_logger_module,
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    logger_module = load_logger_module()

    logger = logger_module.get_logger("tests.logger.bootstrap")

    assert logger_module._BOOTSTRAPPED is True
    assert logging.getLogger().level == logging.DEBUG
    assert logger.getEffectiveLevel() == logging.DEBUG
    assert logger_module._FILE_HANDLER is not None


def test_bootstrap_logging_is_idempotent_and_reuses_handlers(
    monkeypatch: pytest.MonkeyPatch,
    load_logger_module,
) -> None:
    monkeypatch.setenv("LOG_FILE", "output/__pytest__/runtime-idempotent.log")
    logger_module = load_logger_module()

    logger_module.bootstrap_logging()
    root_logger = logging.getLogger()
    console_handler = logger_module._CONSOLE_HANDLER
    file_handler = logger_module._FILE_HANDLER

    logger_module.bootstrap_logging()

    assert console_handler is logger_module._CONSOLE_HANDLER
    assert file_handler is logger_module._FILE_HANDLER
    assert root_logger.handlers.count(console_handler) == 1
    assert root_logger.handlers.count(file_handler) == 1


def test_bootstrap_logging_resolves_relative_paths_from_repo_root(
    monkeypatch: pytest.MonkeyPatch,
    repo_tmp_dir: Path,
    load_logger_module,
) -> None:
    monkeypatch.chdir(repo_tmp_dir)
    monkeypatch.setenv("LOG_FILE", "output/__pytest__/runtime-relative.log")
    logger_module = load_logger_module()

    logger_module.bootstrap_logging()

    file_handler = logger_module._FILE_HANDLER
    assert file_handler is not None
    expected_path = (REPO_ROOT / "output" / "__pytest__" / "runtime-relative.log").resolve()
    assert Path(file_handler.baseFilename).resolve() == expected_path


def test_bootstrap_logging_uses_output_dir_under_repo_root(
    monkeypatch: pytest.MonkeyPatch,
    repo_tmp_dir: Path,
    load_logger_module,
) -> None:
    monkeypatch.chdir(repo_tmp_dir)
    logger_module = load_logger_module()

    logger_module.bootstrap_logging(output_dir="artifacts/__pytest__/run-1")

    file_handler = logger_module._FILE_HANDLER
    assert file_handler is not None
    expected_path = (REPO_ROOT / "artifacts" / "__pytest__" / "run-1" / "runtime.log").resolve()
    assert Path(file_handler.baseFilename).resolve() == expected_path
