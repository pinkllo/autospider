"""异步文件与目录操作工具。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Callable

from loguru import logger

try:
    import aiofiles
    import aiofiles.os
except ImportError as exc:
    raise ImportError(
        "aiofiles is required for async file operations. Install it with: uv add aiofiles"
    ) from exc


async def ensure_directory(path: str | Path) -> bool:
    """异步确保目录存在。"""
    try:
        directory = Path(path)
        if not directory.exists():
            await asyncio.to_thread(directory.mkdir, parents=True, exist_ok=True)
            logger.debug(f"Created directory: {directory}")
        return True
    except Exception as exc:
        logger.error(f"[ASYNC_FS_CREATE_ERROR] Failed to create directory {path}: {exc}")
        return False


async def remove_directory(path: str | Path, force: bool = False) -> bool:
    """异步删除目录。"""
    try:
        directory = Path(path)
        if not directory.exists():
            logger.warning(f"Directory not found: {path}")
            return False

        if force:
            await asyncio.to_thread(shutil.rmtree, directory)
        else:
            await asyncio.to_thread(directory.rmdir)

        logger.debug(f"Removed directory: {directory}")
        return True
    except Exception as exc:
        logger.error(f"[ASYNC_FS_REMOVE_ERROR] Failed to remove directory {path}: {exc}")
        return False


async def list_files(directory: str | Path, pattern: str = "*", recursive: bool = False) -> list[Path]:
    """异步列出目录中的文件。"""
    try:
        root = Path(directory)
        if not root.exists() or not root.is_dir():
            logger.warning(f"Directory not found or not a directory: {directory}")
            return []

        if recursive:
            return await asyncio.to_thread(lambda: list(root.rglob(pattern)))
        return await asyncio.to_thread(lambda: list(root.glob(pattern)))
    except Exception as exc:
        logger.error(f"[ASYNC_FS_LIST_ERROR] Failed to list files in {directory}: {exc}")
        return []


async def save_file(file_path: str | Path, data: Any, encoding: str = "utf-8") -> bool:
    """异步保存数据到文件。"""
    try:
        path = Path(file_path)
        if not path.parent.exists():
            await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)

        if isinstance(data, bytes):
            async with aiofiles.open(path, "wb") as handle:
                await handle.write(data)
        elif isinstance(data, (dict, list)):
            async with aiofiles.open(path, "w", encoding=encoding) as handle:
                await handle.write(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            async with aiofiles.open(path, "w", encoding=encoding) as handle:
                await handle.write(str(data))

        logger.debug(f"Saved file: {path}")
        return True
    except Exception as exc:
        logger.error(f"[ASYNC_FS_SAVE_ERROR] Failed to save {file_path}: {exc}")
        return False


async def load_file(
    file_path: str | Path,
    as_json: bool = False,
    encoding: str = "utf-8",
) -> str | bytes | dict[str, Any] | list[Any] | None:
    """异步读取文件数据。"""
    path = Path(file_path)
    if not path.exists():
        logger.warning(f"[ASYNC_FS_READ_WARN] File not found: {file_path}")
        return None

    try:
        if as_json:
            async with aiofiles.open(path, "r", encoding=encoding) as handle:
                return json.loads(await handle.read())

        try:
            async with aiofiles.open(path, "r", encoding=encoding) as handle:
                return await handle.read()
        except UnicodeDecodeError:
            async with aiofiles.open(path, "rb") as handle:
                return await handle.read()
    except Exception as exc:
        logger.error(f"[ASYNC_FS_READ_ERROR] Failed to read {file_path}: {exc}")
        return None


async def remove_file(file_path: str | Path) -> bool:
    """异步删除文件。"""
    try:
        path = Path(file_path)
        if not path.exists():
            logger.warning(f"File not found: {file_path}")
            return False

        await aiofiles.os.remove(path)
        logger.debug(f"Removed file: {path}")
        return True
    except Exception as exc:
        logger.error(f"[ASYNC_FS_REMOVE_ERROR] Failed to remove {file_path}: {exc}")
        return False


async def copy_file(src: str | Path, dst: str | Path, overwrite: bool = False) -> bool:
    """异步复制文件。"""
    try:
        src_path = Path(src)
        dst_path = Path(dst)

        if not src_path.exists():
            logger.error(f"Source file not found: {src}")
            return False

        if dst_path.exists() and not overwrite:
            logger.warning(f"Destination file already exists: {dst}")
            return False

        await asyncio.to_thread(dst_path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copy2, src_path, dst_path)
        logger.debug(f"Copied file: {src} -> {dst}")
        return True
    except Exception as exc:
        logger.error(f"[ASYNC_FS_COPY_ERROR] Failed to copy {src} to {dst}: {exc}")
        return False


async def move_file(src: str | Path, dst: str | Path, overwrite: bool = False) -> bool:
    """异步移动或重命名文件。"""
    try:
        src_path = Path(src)
        dst_path = Path(dst)

        if not src_path.exists():
            logger.error(f"Source file not found: {src}")
            return False

        if dst_path.exists() and not overwrite:
            logger.warning(f"Destination file already exists: {dst}")
            return False

        await asyncio.to_thread(dst_path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.move, str(src_path), str(dst_path))
        logger.debug(f"Moved file: {src} -> {dst}")
        return True
    except Exception as exc:
        logger.error(f"[ASYNC_FS_MOVE_ERROR] Failed to move {src} to {dst}: {exc}")
        return False


async def get_file_size(file_path: str | Path) -> int | None:
    """异步获取文件大小。"""
    try:
        path = Path(file_path)
        if not path.exists():
            logger.warning(f"File not found: {file_path}")
            return None
        return (await asyncio.to_thread(path.stat)).st_size
    except Exception as exc:
        logger.error(f"[ASYNC_FS_SIZE_ERROR] Failed to get size of {file_path}: {exc}")
        return None


async def file_exists(file_path: str | Path) -> bool:
    """异步检查文件是否存在。"""
    return await asyncio.to_thread(Path(file_path).exists)


async def is_file(path: str | Path) -> bool:
    """异步检查路径是否为文件。"""
    return await asyncio.to_thread(Path(path).is_file)


async def is_directory(path: str | Path) -> bool:
    """异步检查路径是否为目录。"""
    return await asyncio.to_thread(Path(path).is_dir)


async def calculate_file_hash(
    file_path: str | Path,
    algorithm: str = "md5",
    chunk_size: int = 8192,
) -> str | None:
    """异步计算文件哈希值。"""
    path = Path(file_path)
    if not path.exists():
        logger.warning(f"[ASYNC_FS_HASH_WARN] File not found: {file_path}")
        return None

    try:
        hasher = hashlib.new(algorithm)
        async with aiofiles.open(path, "rb") as handle:
            while chunk := await handle.read(chunk_size):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception as exc:
        logger.error(f"[ASYNC_FS_HASH_ERROR] Failed to calculate hash for {file_path}: {exc}")
        return None


async def is_same_file(path_a: str | Path, path_b: str | Path) -> bool:
    """异步判断两个文件是否完全相同。"""
    left = Path(path_a)
    right = Path(path_b)

    if not await file_exists(left) or not await file_exists(right):
        logger.warning(f"[ASYNC_FS_COMPARE_WARN] One or both files do not exist: {left}, {right}")
        return False

    if left.resolve() == right.resolve():
        return True

    try:
        if await get_file_size(left) != await get_file_size(right):
            logger.debug("Files differ in size.")
            return False

        left_hash, right_hash = await asyncio.gather(
            calculate_file_hash(left),
            calculate_file_hash(right),
        )
        is_match = left_hash is not None and left_hash == right_hash

        if is_match:
            logger.debug(f"Files are identical: {left.name} == {right.name}")
        else:
            logger.debug(f"Files content differ: {left.name} != {right.name}")
        return is_match
    except Exception as exc:
        logger.error(f"[ASYNC_FS_COMPARE_ERROR] Error comparing files: {exc}")
        return False


async def save_json(file_path: str | Path, data: dict[str, Any] | list[Any], indent: int = 2) -> bool:
    """异步保存 JSON 数据。"""
    return await save_file(file_path, data)


async def load_json(file_path: str | Path) -> dict[str, Any] | list[Any] | None:
    """异步加载 JSON 数据。"""
    return await load_file(file_path, as_json=True)


async def batch_process_files(
    directory: str | Path,
    pattern: str,
    processor: Callable[[Path], Any],
    recursive: bool = False,
    max_concurrent: int = 10,
) -> dict[str, Any]:
    """异步批量处理匹配文件。"""
    results: dict[str, Any] = {}
    files = await list_files(directory, pattern, recursive)
    semaphore = asyncio.Semaphore(max_concurrent)

    async def process_with_semaphore(file_path: Path) -> tuple[str, Any]:
        async with semaphore:
            try:
                if asyncio.iscoroutinefunction(processor):
                    result = await processor(file_path)
                else:
                    result = await asyncio.to_thread(processor, file_path)
                return str(file_path), result
            except Exception as exc:
                logger.error(f"[ASYNC_BATCH_ERROR] Failed to process {file_path}: {exc}")
                return str(file_path), None

    for file_path, result in await asyncio.gather(*(process_with_semaphore(path) for path in files)):
        results[file_path] = result
    return results


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
]
