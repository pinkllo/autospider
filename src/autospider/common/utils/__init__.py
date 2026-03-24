"""通用工具模块"""

from .file_utils import (
    batch_process_files,
    calculate_file_hash,
    copy_file,
    ensure_directory,
    file_exists,
    get_file_size,
    is_directory,
    is_file,
    is_same_file,
    list_files,
    load_file,
    load_json,
    move_file,
    remove_directory,
    remove_file,
    save_file,
    save_json,
)
from .fuzzy_search import (
    FuzzyTextSearcher,
    TextMatch,
    search_text_in_html,
)

__all__ = [
    "ensure_directory",
    "remove_directory",
    "list_files",
    "save_file",
    "load_file",
    "remove_file",
    "copy_file",
    "move_file",
    "get_file_size",
    "file_exists",
    "is_file",
    "is_directory",
    "calculate_file_hash",
    "is_same_file",
    "save_json",
    "load_json",
    "batch_process_files",
    "FuzzyTextSearcher",
    "TextMatch",
    "search_text_in_html",
]
