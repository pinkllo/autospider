# Async File Utils

`file_utils_async.py` 提供了高性能的异步文件系统操作接口。

---

## 📑 核心函数

### 目录操作
- `ensure_directory(path)`: 异步确保目录存在（不存在则创建）。
- `remove_directory(path, force=False)`: 异步删除目录。
- `list_files(directory, pattern="*", recursive=False)`: 异步列出匹配文件。

### 文件读写
- `read_text_async(file_path)`: 异步读取文本文件。
- `write_text_async(file_path, content)`: 异步写入文本文件。
- `save_json_async(file_path, data)`: 异步保存数据为 JSON。
- `load_json_async(file_path)`: 异步加载 JSON 数据。

### 文件管理
- `copy_file_async(src, dst)`: 异步复制文件。
- `move_file_async(src, dst)`: 异步移动文件。
- `calculate_hash_async(file_path, algorithm="sha256")`: 异步计算文件哈希值。
