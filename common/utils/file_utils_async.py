"""
异步文件/文件夹操作工具模块
基于 aiofiles 和 asyncio，提供高性能的异步文件系统操作

主要功能：
- 异步文件/文件夹的创建、读取、写入、删除
- 异步文件哈希计算和比较
- 异步 JSON 数据的保存和加载
- 异步文件复制、移动
- 异步批量文件处理

使用场景：
- 高并发 Web 应用（FastAPI、aiohttp）
- 需要同时处理大量文件
- 与其他异步代码集成
"""

import json
import hashlib
import shutil
import asyncio
from pathlib import Path
from typing import Any, Union, Dict, List, Optional, Callable
from loguru import logger

try:
    import aiofiles
    import aiofiles.os
except ImportError:
    raise ImportError(
        "aiofiles is required for async file operations. "
        "Install it with: uv add aiofiles"
    )


# ==================== 目录操作 ====================

async def ensure_directory(path: Union[str, Path]) -> bool:
    """
    异步确保目录存在，如果不存在则创建
    
    Args:
        path: 目录路径
        
    Returns:
        bool: 成功返回 True，失败返回 False
    """
    try:
        p = Path(path)
        if not p.exists():
            await asyncio.to_thread(p.mkdir, parents=True, exist_ok=True)
            logger.debug(f"Created directory: {p}")
        return True
    except Exception as e:
        logger.error(f"[ASYNC_FS_CREATE_ERROR] Failed to create directory {path}: {e}")
        return False


async def remove_directory(path: Union[str, Path], force: bool = False) -> bool:
    """
    异步删除目录
    
    Args:
        path: 目录路径
        force: 是否强制删除非空目录
        
    Returns:
        bool: 成功返回 True，失败返回 False
    """
    try:
        p = Path(path)
        if not p.exists():
            logger.warning(f"Directory not found: {path}")
            return False
        
        if force:
            await asyncio.to_thread(shutil.rmtree, p)
        else:
            await asyncio.to_thread(p.rmdir)
        
        logger.debug(f"Removed directory: {p}")
        return True
    except Exception as e:
        logger.error(f"[ASYNC_FS_REMOVE_ERROR] Failed to remove directory {path}: {e}")
        return False


async def list_files(
    directory: Union[str, Path],
    pattern: str = "*",
    recursive: bool = False
) -> List[Path]:
    """
    异步列出目录中的文件
    
    Args:
        directory: 目录路径
        pattern: 文件匹配模式
        recursive: 是否递归搜索子目录
        
    Returns:
        List[Path]: 文件路径列表
    """
    try:
        p = Path(directory)
        if not p.exists() or not p.is_dir():
            logger.warning(f"Directory not found or not a directory: {directory}")
            return []
        
        if recursive:
            files = await asyncio.to_thread(lambda: list(p.rglob(pattern)))
        else:
            files = await asyncio.to_thread(lambda: list(p.glob(pattern)))
        
        return files
    except Exception as e:
        logger.error(f"[ASYNC_FS_LIST_ERROR] Failed to list files in {directory}: {e}")
        return []


# ==================== 文件操作 ====================

async def save_file(file_path: Union[str, Path], data: Any, encoding: str = "utf-8") -> bool:
    """
    异步保存数据到文件（智能识别类型）
    
    Args:
        file_path: 文件路径
        data: 要保存的数据
        encoding: 文本编码
        
    Returns:
        bool: 成功返回 True，失败返回 False
    """
    try:
        path = Path(file_path)
        
        # 自动创建父目录
        if not path.parent.exists():
            await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        
        # 根据数据类型写入
        if isinstance(data, bytes):
            async with aiofiles.open(path, "wb") as f:
                await f.write(data)
        elif isinstance(data, (dict, list)):
            async with aiofiles.open(path, "w", encoding=encoding) as f:
                await f.write(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            async with aiofiles.open(path, "w", encoding=encoding) as f:
                await f.write(str(data))
        
        logger.debug(f"Saved file: {path}")
        return True
    except Exception as e:
        logger.error(f"[ASYNC_FS_SAVE_ERROR] Failed to save {file_path}: {e}")
        return False


async def load_file(
    file_path: Union[str, Path],
    as_json: bool = False,
    encoding: str = "utf-8"
) -> Union[str, bytes, dict, list, None]:
    """
    异步读取文件数据
    
    Args:
        file_path: 文件路径
        as_json: 是否解析为 JSON
        encoding: 文本编码
        
    Returns:
        文件内容，失败返回 None
    """
    path = Path(file_path)
    if not path.exists():
        logger.warning(f"[ASYNC_FS_READ_WARN] File not found: {file_path}")
        return None
    
    try:
        if as_json:
            async with aiofiles.open(path, "r", encoding=encoding) as f:
                content = await f.read()
                return json.loads(content)
        
        # 尝试文本读取
        try:
            async with aiofiles.open(path, "r", encoding=encoding) as f:
                return await f.read()
        except UnicodeDecodeError:
            # 回退到二进制读取
            async with aiofiles.open(path, "rb") as f:
                return await f.read()
    except Exception as e:
        logger.error(f"[ASYNC_FS_READ_ERROR] Failed to read {file_path}: {e}")
        return None


async def remove_file(file_path: Union[str, Path]) -> bool:
    """
    异步删除文件
    
    Args:
        file_path: 文件路径
        
    Returns:
        bool: 成功返回 True，失败返回 False
    """
    try:
        path = Path(file_path)
        if not path.exists():
            logger.warning(f"File not found: {file_path}")
            return False
        
        await aiofiles.os.remove(path)
        logger.debug(f"Removed file: {path}")
        return True
    except Exception as e:
        logger.error(f"[ASYNC_FS_REMOVE_ERROR] Failed to remove {file_path}: {e}")
        return False


async def copy_file(
    src: Union[str, Path],
    dst: Union[str, Path],
    overwrite: bool = False
) -> bool:
    """
    异步复制文件
    
    Args:
        src: 源文件路径
        dst: 目标文件路径
        overwrite: 是否覆盖已存在的文件
        
    Returns:
        bool: 成功返回 True，失败返回 False
    """
    try:
        src_path = Path(src)
        dst_path = Path(dst)
        
        if not src_path.exists():
            logger.error(f"Source file not found: {src}")
            return False
        
        if dst_path.exists() and not overwrite:
            logger.warning(f"Destination file already exists: {dst}")
            return False
        
        # 确保目标目录存在
        await asyncio.to_thread(dst_path.parent.mkdir, parents=True, exist_ok=True)
        
        # 异步复制文件
        await asyncio.to_thread(shutil.copy2, src_path, dst_path)
        logger.debug(f"Copied file: {src} -> {dst}")
        return True
    except Exception as e:
        logger.error(f"[ASYNC_FS_COPY_ERROR] Failed to copy {src} to {dst}: {e}")
        return False


async def move_file(
    src: Union[str, Path],
    dst: Union[str, Path],
    overwrite: bool = False
) -> bool:
    """
    异步移动/重命名文件
    
    Args:
        src: 源文件路径
        dst: 目标文件路径
        overwrite: 是否覆盖已存在的文件
        
    Returns:
        bool: 成功返回 True，失败返回 False
    """
    try:
        src_path = Path(src)
        dst_path = Path(dst)
        
        if not src_path.exists():
            logger.error(f"Source file not found: {src}")
            return False
        
        if dst_path.exists() and not overwrite:
            logger.warning(f"Destination file already exists: {dst}")
            return False
        
        # 确保目标目录存在
        await asyncio.to_thread(dst_path.parent.mkdir, parents=True, exist_ok=True)
        
        await asyncio.to_thread(shutil.move, str(src_path), str(dst_path))
        logger.debug(f"Moved file: {src} -> {dst}")
        return True
    except Exception as e:
        logger.error(f"[ASYNC_FS_MOVE_ERROR] Failed to move {src} to {dst}: {e}")
        return False


# ==================== 文件信息 ====================

async def get_file_size(file_path: Union[str, Path]) -> Optional[int]:
    """
    异步获取文件大小（字节）
    
    Args:
        file_path: 文件路径
        
    Returns:
        int: 文件大小，失败返回 None
    """
    try:
        path = Path(file_path)
        if not path.exists():
            logger.warning(f"File not found: {file_path}")
            return None
        stat = await asyncio.to_thread(path.stat)
        return stat.st_size
    except Exception as e:
        logger.error(f"[ASYNC_FS_SIZE_ERROR] Failed to get size of {file_path}: {e}")
        return None


async def file_exists(file_path: Union[str, Path]) -> bool:
    """
    异步检查文件是否存在
    
    Args:
        file_path: 文件路径
        
    Returns:
        bool: 存在返回 True，否则返回 False
    """
    return await asyncio.to_thread(Path(file_path).exists)


async def is_file(path: Union[str, Path]) -> bool:
    """
    异步检查路径是否为文件
    
    Args:
        path: 路径
        
    Returns:
        bool: 是文件返回 True，否则返回 False
    """
    return await asyncio.to_thread(Path(path).is_file)


async def is_directory(path: Union[str, Path]) -> bool:
    """
    异步检查路径是否为目录
    
    Args:
        path: 路径
        
    Returns:
        bool: 是目录返回 True，否则返回 False
    """
    return await asyncio.to_thread(Path(path).is_dir)


# ==================== 文件哈希和比较 ====================

async def calculate_file_hash(
    file_path: Union[str, Path],
    algorithm: str = "md5",
    chunk_size: int = 8192
) -> Optional[str]:
    """
    异步计算文件哈希值
    
    Args:
        file_path: 文件路径
        algorithm: 哈希算法
        chunk_size: 分块读取大小
        
    Returns:
        str: 哈希值，失败返回 None
    """
    path = Path(file_path)
    if not path.exists():
        logger.warning(f"[ASYNC_FS_HASH_WARN] File not found: {file_path}")
        return None
    
    try:
        hasher = hashlib.new(algorithm)
        async with aiofiles.open(path, "rb") as f:
            while chunk := await f.read(chunk_size):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception as e:
        logger.error(f"[ASYNC_FS_HASH_ERROR] Failed to calculate hash for {file_path}: {e}")
        return None


async def is_same_file(path_a: Union[str, Path], path_b: Union[str, Path]) -> bool:
    """
    异步判断两个文件是否完全相同
    
    Args:
        path_a: 文件A路径
        path_b: 文件B路径
        
    Returns:
        bool: 相同返回 True，否则返回 False
    """
    p1 = Path(path_a)
    p2 = Path(path_b)
    
    # 检查存在性
    exists_a = await file_exists(p1)
    exists_b = await file_exists(p2)
    
    if not exists_a or not exists_b:
        logger.warning(f"[ASYNC_FS_COMPARE_WARN] One or both files do not exist: {p1}, {p2}")
        return False
    
    # 路径相同
    if p1.resolve() == p2.resolve():
        return True
    
    try:
        # 比较文件大小
        size_a = await get_file_size(p1)
        size_b = await get_file_size(p2)
        
        if size_a != size_b:
            logger.debug(f"Files differ in size: {size_a} != {size_b}")
            return False
        
        # 比较哈希值
        hash_a, hash_b = await asyncio.gather(
            calculate_file_hash(p1),
            calculate_file_hash(p2)
        )
        
        is_match = (hash_a == hash_b) and (hash_a is not None)
        
        if is_match:
            logger.debug(f"Files are identical: {p1.name} == {p2.name}")
        else:
            logger.debug(f"Files content differ: {p1.name} != {p2.name}")
        
        return is_match
    except Exception as e:
        logger.error(f"[ASYNC_FS_COMPARE_ERROR] Error comparing files: {e}")
        return False


# ==================== JSON 操作 ====================

async def save_json(file_path: Union[str, Path], data: Union[dict, list], indent: int = 2) -> bool:
    """
    异步保存 JSON 数据到文件
    
    Args:
        file_path: 文件路径
        data: 要保存的数据
        indent: 缩进空格数
        
    Returns:
        bool: 成功返回 True，失败返回 False
    """
    return await save_file(file_path, data)


async def load_json(file_path: Union[str, Path]) -> Union[dict, list, None]:
    """
    异步从文件加载 JSON 数据
    
    Args:
        file_path: 文件路径
        
    Returns:
        dict/list: JSON 数据，失败返回 None
    """
    return await load_file(file_path, as_json=True)


# ==================== 批量操作 ====================

async def batch_process_files(
    directory: Union[str, Path],
    pattern: str,
    processor: Callable[[Path], Any],
    recursive: bool = False,
    max_concurrent: int = 10
) -> Dict[str, Any]:
    """
    异步批量处理文件
    
    Args:
        directory: 目录路径
        pattern: 文件匹配模式
        processor: 处理函数（可以是同步或异步函数）
        recursive: 是否递归处理子目录
        max_concurrent: 最大并发数
        
    Returns:
        Dict[str, Any]: 文件路径到处理结果的映射
    """
    results = {}
    files = await list_files(directory, pattern, recursive)
    
    # 创建信号量限制并发数
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def process_with_semaphore(file_path: Path):
        async with semaphore:
            try:
                # 检查处理函数是否为协程函数
                if asyncio.iscoroutinefunction(processor):
                    result = await processor(file_path)
                else:
                    result = await asyncio.to_thread(processor, file_path)
                return str(file_path), result
            except Exception as e:
                logger.error(f"[ASYNC_BATCH_ERROR] Failed to process {file_path}: {e}")
                return str(file_path), None
    
    # 并发处理所有文件
    tasks = [process_with_semaphore(f) for f in files]
    completed = await asyncio.gather(*tasks)
    
    # 构建结果字典
    for file_path, result in completed:
        results[file_path] = result
    
    return results


# ==================== 导出所有函数 ====================

__all__ = [
    # 目录操作
    "ensure_directory",
    "remove_directory",
    "list_files",
    
    # 文件操作
    "save_file",
    "load_file",
    "remove_file",
    "copy_file",
    "move_file",
    
    # 文件信息
    "get_file_size",
    "file_exists",
    "is_file",
    "is_directory",
    
    # 哈希和比较
    "calculate_file_hash",
    "is_same_file",
    
    # JSON 操作
    "save_json",
    "load_json",
    
    # 批量操作
    "batch_process_files",
]
