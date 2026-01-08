# file_utils.py - 文件操作工具

file_utils.py 模块提供文件/文件夹操作工具函数。

---

## 📁 文件路径

```
common/utils/file_utils.py
```

---

## 📑 函数目录

### 🚀 核心函数
- `ensure_directory()` - 确保目录存在
- `remove_directory()` - 删除目录
- `read_file()` - 读取文件
- `write_file()` - 写入文件
- `read_json()` - 读取 JSON 文件
- `write_json()` - 写入 JSON 文件

---

## 🚀 核心功能

### ensure_directory

确保目录存在，如果不存在则创建。

```python
from common.utils.file_utils import ensure_directory

# 确保目录存在
ensure_directory("data/output")
```

### read_json / write_json

读取和写入 JSON 文件。

```python
from common.utils.file_utils import read_json, write_json

# 读取 JSON
data = read_json("config.json")

# 写入 JSON
write_json("output.json", {"key": "value"})
```

---

## 🔧 使用示例

### 基本使用

```python
from common.utils.file_utils import (
    ensure_directory,
    read_file,
    write_file,
    read_json,
    write_json
)

# 确保目录存在
ensure_directory("data/output")

# 读取文件
content = read_file("input.txt")

# 写入文件
write_file("output.txt", "Hello World")

# 读取 JSON
data = read_json("config.json")

# 写入 JSON
write_json("output.json", {"key": "value"})
```

---

## 📚 函数参考

### 函数列表

| 函数 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `ensure_directory()` | path | bool | 确保目录存在 |
| `remove_directory()` | path | bool | 删除目录 |
| `read_file()` | path | str | 读取文件 |
| `write_file()` | path, content | None | 写入文件 |
| `read_json()` | path | dict | 读取 JSON 文件 |
| `write_json()` | path, data | None | 写入 JSON 文件 |

---

*最后更新: 2026-01-08*
