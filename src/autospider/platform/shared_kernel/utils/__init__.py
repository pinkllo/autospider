"""通用工具模块。"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_FILE_UTIL_EXPORTS = {
    "batch_process_files",
    "calculate_file_hash",
    "copy_file",
    "ensure_directory",
    "file_exists",
    "get_file_size",
    "is_directory",
    "is_file",
    "is_same_file",
    "list_files",
    "load_file",
    "load_json",
    "move_file",
    "remove_directory",
    "remove_file",
    "save_file",
    "save_json",
}
_FUZZY_EXPORTS = {
    "FuzzyTextSearcher",
    "TextMatch",
    "search_text_in_html",
}
_PATH_EXPORTS = {
    "get_package_root",
    "get_prompt_path",
    "get_repo_root",
    "resolve_output_path",
    "resolve_repo_path",
}

__all__ = sorted(_FILE_UTIL_EXPORTS | _FUZZY_EXPORTS | _PATH_EXPORTS)


def __getattr__(name: str) -> Any:
    if name in _FILE_UTIL_EXPORTS:
        module = import_module(".file_utils", __name__)
        return getattr(module, name)
    if name in _FUZZY_EXPORTS:
        module = import_module(".fuzzy_search", __name__)
        return getattr(module, name)
    if name in _PATH_EXPORTS:
        module = import_module(".paths", __name__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
