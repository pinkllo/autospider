from __future__ import annotations

from importlib import import_module

_EXPORTS = {
    "BenchmarkPaths": "run_benchmark",
    "BenchmarkReportService": "run_benchmark",
    "ResumeRun": "resume",
    "RunChatPipeline": "run_chat_pipeline",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    module = import_module(f"{__name__}.{module_name}")
    return getattr(module, name)
