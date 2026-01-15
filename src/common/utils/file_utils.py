"""
通用文件/文件夹操作工具模块
整合了 fs.py 和 storage.py 的功能，提供统一的文件系统操作接口

主要功能：
- 文件/文件夹的创建、读取、写入、删除
- 文件哈希计算和比较
- JSON 数据的保存和加载
- 文件复制、移动、重命名
- 目录遍历和文件查找
"""

import json
import hashlib
import shutil
from pathlib import Path
from typing import Any, Union, Dict, List, Optional, Callable
from loguru import logger


# ==================== 目录操作 ====================

def ensure_directory(path: Union[str, Path]) -> bool:
    """
    确保目录存在，如果不存在则创建
    
    Args:
        path: 目录路径
        
    Returns:
        bool: 成功返回 True，失败返回 False
        
    Example:
        >>> ensure_directory("data/output")
        True
    """
    try:
        p = Path(path)
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)
            logger.debug(f"Created directory: {p}")
        return True
    except Exception as e:
        logger.error(f"[FS_CREATE_ERROR] Failed to create directory {path}: {e}")
        return False


def remove_directory(path: Union[str, Path], force: bool = False) -> bool:
    """
    删除目录
    
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
            shutil.rmtree(p)
        else:
            p.rmdir()  # 只删除空目录
        
        logger.debug(f"Removed directory: {p}")
        return True
    except Exception as e:
        logger.error(f"[FS_REMOVE_ERROR] Failed to remove directory {path}: {e}")
        return False


def list_files(
    directory: Union[str, Path],
    pattern: str = "*",
    recursive: bool = False
) -> List[Path]:
    """
    列出目录中的文件
    
    Args:
        directory: 目录路径
        pattern: 文件匹配模式（支持通配符）
        recursive: 是否递归搜索子目录
        
    Returns:
        List[Path]: 文件路径列表
        
    Example:
        >>> list_files("data", "*.json")
        [Path('data/config.json'), Path('data/output.json')]
    """
    try:
        p = Path(directory)
        if not p.exists() or not p.is_dir():
            logger.warning(f"Directory not found or not a directory: {directory}")
            return []
        
        if recursive:
            return list(p.rglob(pattern))
        else:
            return list(p.glob(pattern))
    except Exception as e:
        logger.error(f"[FS_LIST_ERROR] Failed to list files in {directory}: {e}")
        return []


# ==================== 文件操作 ====================

def save_file(file_path: Union[str, Path], data: Any, encoding: str = "utf-8") -> bool:
    """
    保存数据到文件（智能识别类型）
    
    Args:
        file_path: 文件路径
        data: 要保存的数据
            - dict/list: 自动转为 JSON
            - bytes: 写入二进制
            - 其他: 转为字符串写入
        encoding: 文本编码（默认 utf-8）
        
    Returns:
        bool: 成功返回 True，失败返回 False
        
    Example:
        >>> save_file("data.json", {"key": "value"})
        True
        >>> save_file("image.png", image_bytes)
        True
    """
    try:
        path = Path(file_path)
        
        # 自动创建父目录
        if not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
        
        # 根据数据类型写入
        if isinstance(data, bytes):
            with open(path, "wb") as f:
                f.write(data)
        elif isinstance(data, (dict, list)):
            with open(path, "w", encoding=encoding) as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        else:
            with open(path, "w", encoding=encoding) as f:
                f.write(str(data))
        
        logger.debug(f"Saved file: {path}")
        return True
    except Exception as e:
        logger.error(f"[FS_SAVE_ERROR] Failed to save {file_path}: {e}")
        return False


def load_file(
    file_path: Union[str, Path],
    as_json: bool = False,
    encoding: str = "utf-8"
) -> Union[str, bytes, dict, list, None]:
    """
    读取文件数据
    
    Args:
        file_path: 文件路径
        as_json: 是否解析为 JSON
        encoding: 文本编码（默认 utf-8）
        
    Returns:
        文件内容，失败返回 None
        
    Example:
        >>> load_file("data.json", as_json=True)
        {"key": "value"}
        >>> load_file("text.txt")
        "Hello World"
    """
    path = Path(file_path)
    if not path.exists():
        logger.warning(f"[FS_READ_WARN] File not found: {file_path}")
        return None
    
    try:
        if as_json:
            with open(path, "r", encoding=encoding) as f:
                return json.load(f)
        
        # 尝试文本读取
        try:
            with open(path, "r", encoding=encoding) as f:
                return f.read()
        except UnicodeDecodeError:
            # 回退到二进制读取
            with open(path, "rb") as f:
                return f.read()
    except Exception as e:
        logger.error(f"[FS_READ_ERROR] Failed to read {file_path}: {e}")
        return None


def remove_file(file_path: Union[str, Path]) -> bool:
    """
    删除文件
    
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
        
        path.unlink()
        logger.debug(f"Removed file: {path}")
        return True
    except Exception as e:
        logger.error(f"[FS_REMOVE_ERROR] Failed to remove {file_path}: {e}")
        return False


def copy_file(
    src: Union[str, Path],
    dst: Union[str, Path],
    overwrite: bool = False
) -> bool:
    """
    复制文件
    
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
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        
        shutil.copy2(src_path, dst_path)
        logger.debug(f"Copied file: {src} -> {dst}")
        return True
    except Exception as e:
        logger.error(f"[FS_COPY_ERROR] Failed to copy {src} to {dst}: {e}")
        return False


def move_file(
    src: Union[str, Path],
    dst: Union[str, Path],
    overwrite: bool = False
) -> bool:
    """
    移动/重命名文件
    
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
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        
        shutil.move(str(src_path), str(dst_path))
        logger.debug(f"Moved file: {src} -> {dst}")
        return True
    except Exception as e:
        logger.error(f"[FS_MOVE_ERROR] Failed to move {src} to {dst}: {e}")
        return False


# ==================== 文件信息 ====================

def get_file_size(file_path: Union[str, Path]) -> Optional[int]:
    """
    获取文件大小（字节）
    
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
        return path.stat().st_size
    except Exception as e:
        logger.error(f"[FS_SIZE_ERROR] Failed to get size of {file_path}: {e}")
        return None


def file_exists(file_path: Union[str, Path]) -> bool:
    """
    检查文件是否存在
    
    Args:
        file_path: 文件路径
        
    Returns:
        bool: 存在返回 True，否则返回 False
    """
    return Path(file_path).exists()


def is_file(path: Union[str, Path]) -> bool:
    """
    检查路径是否为文件
    
    Args:
        path: 路径
        
    Returns:
        bool: 是文件返回 True，否则返回 False
    """
    return Path(path).is_file()


def is_directory(path: Union[str, Path]) -> bool:
    """
    检查路径是否为目录
    
    Args:
        path: 路径
        
    Returns:
        bool: 是目录返回 True，否则返回 False
    """
    return Path(path).is_dir()


# ==================== 文件哈希和比较 ====================

def calculate_file_hash(
    file_path: Union[str, Path],
    algorithm: str = "md5",
    chunk_size: int = 8192
) -> Optional[str]:
    """
    计算文件哈希值
    
    Args:
        file_path: 文件路径
        algorithm: 哈希算法（md5, sha1, sha256 等）
        chunk_size: 分块读取大小（字节）
        
    Returns:
        str: 哈希值，失败返回 None
        
    Example:
        >>> calculate_file_hash("file.txt", "md5")
        "5d41402abc4b2a76b9719d911017c592"
    """
    path = Path(file_path)
    if not path.exists():
        logger.warning(f"[FS_HASH_WARN] File not found: {file_path}")
        return None
    
    try:
        hasher = hashlib.new(algorithm)
        with open(path, "rb") as f:
            while chunk := f.read(chunk_size):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception as e:
        logger.error(f"[FS_HASH_ERROR] Failed to calculate hash for {file_path}: {e}")
        return None


def is_same_file(path_a: Union[str, Path], path_b: Union[str, Path]) -> bool:
    """
    判断两个文件是否完全相同
    
    策略：
    1. 检查文件是否存在
    2. 比较文件大小（快速）
    3. 比较 MD5 哈希值（精确）
    
    Args:
        path_a: 文件A路径
        path_b: 文件B路径
        
    Returns:
        bool: 相同返回 True，否则返回 False
    """
    p1 = Path(path_a)
    p2 = Path(path_b)
    
    # 检查存在性
    if not p1.exists() or not p2.exists():
        logger.warning(f"[FS_COMPARE_WARN] One or both files do not exist: {p1}, {p2}")
        return False
    
    # 路径相同
    if p1.resolve() == p2.resolve():
        return True
    
    try:
        # 比较文件大小
        size_a = p1.stat().st_size
        size_b = p2.stat().st_size
        
        if size_a != size_b:
            logger.debug(f"Files differ in size: {size_a} != {size_b}")
            return False
        
        # 比较哈希值
        hash_a = calculate_file_hash(p1)
        hash_b = calculate_file_hash(p2)
        
        is_match = (hash_a == hash_b) and (hash_a is not None)
        
        if is_match:
            logger.debug(f"Files are identical: {p1.name} == {p2.name}")
        else:
            logger.debug(f"Files content differ: {p1.name} != {p2.name}")
        
        return is_match
    except Exception as e:
        logger.error(f"[FS_COMPARE_ERROR] Error comparing files: {e}")
        return False


# ==================== JSON 操作 ====================

def save_json(file_path: Union[str, Path], data: Union[dict, list], indent: int = 2) -> bool:
    """
    保存 JSON 数据到文件
    
    Args:
        file_path: 文件路径
        data: 要保存的数据（dict 或 list）
        indent: 缩进空格数
        
    Returns:
        bool: 成功返回 True，失败返回 False
    """
    return save_file(file_path, data)


def load_json(file_path: Union[str, Path]) -> Union[dict, list, None]:
    """
    从文件加载 JSON 数据
    
    Args:
        file_path: 文件路径
        
    Returns:
        dict/list: JSON 数据，失败返回 None
    """
    return load_file(file_path, as_json=True)


# ==================== 批量操作 ====================

def batch_process_files(
    directory: Union[str, Path],
    pattern: str,
    processor: Callable[[Path], Any],
    recursive: bool = False
) -> Dict[str, Any]:
    """
    批量处理文件
    
    Args:
        directory: 目录路径
        pattern: 文件匹配模式
        processor: 处理函数，接收 Path 对象
        recursive: 是否递归处理子目录
        
    Returns:
        Dict[str, Any]: 文件路径到处理结果的映射
        
    Example:
        >>> def get_size(path):
        ...     return path.stat().st_size
        >>> batch_process_files("data", "*.txt", get_size)
        {"data/a.txt": 1024, "data/b.txt": 2048}
    """
    results = {}
    files = list_files(directory, pattern, recursive)
    
    for file_path in files:
        try:
            result = processor(file_path)
            results[str(file_path)] = result
        except Exception as e:
            logger.error(f"[BATCH_ERROR] Failed to process {file_path}: {e}")
            results[str(file_path)] = None
    
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
