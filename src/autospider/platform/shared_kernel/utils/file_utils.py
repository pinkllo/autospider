"""通用文件与目录操作工具。"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Callable

from autospider.platform.observability.logger import get_logger

logger = get_logger(__name__)


def ensure_directory(path: str | Path) -> bool:
    """确保目录存在。"""
    try:
        directory = Path(path)
        if not directory.exists():
            directory.mkdir(parents=True, exist_ok=True)
            logger.debug(f"Created directory: {directory}")
        return True
    except Exception as exc:
        logger.error(f"[FS_CREATE_ERROR] Failed to create directory {path}: {exc}")
        return False


def remove_directory(path: str | Path, force: bool = False) -> bool:
    """删除目录。"""
    try:
        directory = Path(path)
        if not directory.exists():
            logger.warning(f"Directory not found: {path}")
            return False

        if force:
            shutil.rmtree(directory)
        else:
            directory.rmdir()

        logger.debug(f"Removed directory: {directory}")
        return True
    except Exception as exc:
        logger.error(f"[FS_REMOVE_ERROR] Failed to remove directory {path}: {exc}")
        return False


def list_files(directory: str | Path, pattern: str = "*", recursive: bool = False) -> list[Path]:
    """列出目录中的文件。"""
    try:
        root = Path(directory)
        if not root.exists() or not root.is_dir():
            logger.warning(f"Directory not found or not a directory: {directory}")
            return []

        return list(root.rglob(pattern) if recursive else root.glob(pattern))
    except Exception as exc:
        logger.error(f"[FS_LIST_ERROR] Failed to list files in {directory}: {exc}")
        return []


def save_file(file_path: str | Path, data: Any, encoding: str = "utf-8") -> bool:
    """保存数据到文件。"""
    try:
        path = Path(file_path)
        if not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)

        if isinstance(data, bytes):
            with open(path, "wb") as handle:
                handle.write(data)
        elif isinstance(data, (dict, list)):
            with open(path, "w", encoding=encoding) as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
        else:
            with open(path, "w", encoding=encoding) as handle:
                handle.write(str(data))

        logger.debug(f"Saved file: {path}")
        return True
    except Exception as exc:
        logger.error(f"[FS_SAVE_ERROR] Failed to save {file_path}: {exc}")
        return False


def load_file(
    file_path: str | Path,
    as_json: bool = False,
    encoding: str = "utf-8",
) -> str | bytes | dict[str, Any] | list[Any] | None:
    """读取文件数据。"""
    path = Path(file_path)
    if not path.exists():
        logger.warning(f"[FS_READ_WARN] File not found: {file_path}")
        return None

    try:
        if as_json:
            with open(path, "r", encoding=encoding) as handle:
                return json.load(handle)

        try:
            with open(path, "r", encoding=encoding) as handle:
                return handle.read()
        except UnicodeDecodeError:
            with open(path, "rb") as handle:
                return handle.read()
    except Exception as exc:
        logger.error(f"[FS_READ_ERROR] Failed to read {file_path}: {exc}")
        return None


def remove_file(file_path: str | Path) -> bool:
    """删除文件。"""
    try:
        path = Path(file_path)
        if not path.exists():
            logger.warning(f"File not found: {file_path}")
            return False

        path.unlink()
        logger.debug(f"Removed file: {path}")
        return True
    except Exception as exc:
        logger.error(f"[FS_REMOVE_ERROR] Failed to remove {file_path}: {exc}")
        return False


def copy_file(src: str | Path, dst: str | Path, overwrite: bool = False) -> bool:
    """复制文件。"""
    try:
        src_path = Path(src)
        dst_path = Path(dst)

        if not src_path.exists():
            logger.error(f"Source file not found: {src}")
            return False

        if dst_path.exists() and not overwrite:
            logger.warning(f"Destination file already exists: {dst}")
            return False

        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dst_path)
        logger.debug(f"Copied file: {src} -> {dst}")
        return True
    except Exception as exc:
        logger.error(f"[FS_COPY_ERROR] Failed to copy {src} to {dst}: {exc}")
        return False


def move_file(src: str | Path, dst: str | Path, overwrite: bool = False) -> bool:
    """移动或重命名文件。"""
    try:
        src_path = Path(src)
        dst_path = Path(dst)

        if not src_path.exists():
            logger.error(f"Source file not found: {src}")
            return False

        if dst_path.exists() and not overwrite:
            logger.warning(f"Destination file already exists: {dst}")
            return False

        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src_path), str(dst_path))
        logger.debug(f"Moved file: {src} -> {dst}")
        return True
    except Exception as exc:
        logger.error(f"[FS_MOVE_ERROR] Failed to move {src} to {dst}: {exc}")
        return False


def get_file_size(file_path: str | Path) -> int | None:
    """获取文件大小。"""
    try:
        path = Path(file_path)
        if not path.exists():
            logger.warning(f"File not found: {file_path}")
            return None
        return path.stat().st_size
    except Exception as exc:
        logger.error(f"[FS_SIZE_ERROR] Failed to get size of {file_path}: {exc}")
        return None


def file_exists(file_path: str | Path) -> bool:
    """检查文件是否存在。"""
    return Path(file_path).exists()


def is_file(path: str | Path) -> bool:
    """检查路径是否为文件。"""
    return Path(path).is_file()


def is_directory(path: str | Path) -> bool:
    """检查路径是否为目录。"""
    return Path(path).is_dir()


def calculate_file_hash(
    file_path: str | Path,
    algorithm: str = "md5",
    chunk_size: int = 8192,
) -> str | None:
    """计算文件哈希值。"""
    path = Path(file_path)
    if not path.exists():
        logger.warning(f"[FS_HASH_WARN] File not found: {file_path}")
        return None

    try:
        hasher = hashlib.new(algorithm)
        with open(path, "rb") as handle:
            while chunk := handle.read(chunk_size):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception as exc:
        logger.error(f"[FS_HASH_ERROR] Failed to calculate hash for {file_path}: {exc}")
        return None


def is_same_file(path_a: str | Path, path_b: str | Path) -> bool:
    """判断两个文件是否完全一致。"""
    left = Path(path_a)
    right = Path(path_b)

    if not left.exists() or not right.exists():
        logger.warning(f"[FS_COMPARE_WARN] One or both files do not exist: {left}, {right}")
        return False

    if left.resolve() == right.resolve():
        return True

    try:
        if left.stat().st_size != right.stat().st_size:
            logger.debug(f"Files differ in size: {left.stat().st_size} != {right.stat().st_size}")
            return False

        left_hash = calculate_file_hash(left)
        right_hash = calculate_file_hash(right)
        is_match = left_hash is not None and left_hash == right_hash

        if is_match:
            logger.debug(f"Files are identical: {left.name} == {right.name}")
        else:
            logger.debug(f"Files content differ: {left.name} != {right.name}")
        return is_match
    except Exception as exc:
        logger.error(f"[FS_COMPARE_ERROR] Error comparing files: {exc}")
        return False


def save_json(file_path: str | Path, data: dict[str, Any] | list[Any], indent: int = 2) -> bool:
    """保存 JSON 数据。"""
    return save_file(file_path, data)


def load_json(file_path: str | Path) -> dict[str, Any] | list[Any] | None:
    """加载 JSON 数据。"""
    return load_file(file_path, as_json=True)


def batch_process_files(
    directory: str | Path,
    pattern: str,
    processor: Callable[[Path], Any],
    recursive: bool = False,
) -> dict[str, Any]:
    """批量处理匹配文件。"""
    results: dict[str, Any] = {}
    for file_path in list_files(directory, pattern, recursive):
        try:
            results[str(file_path)] = processor(file_path)
        except Exception as exc:
            logger.error(f"[BATCH_ERROR] Failed to process {file_path}: {exc}")
            results[str(file_path)] = None
    return results


__all__ = [
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
]
