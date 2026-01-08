# cli.py - CLI 入口

cli.py 模块提供命令行接口，支持运行 Agent 和其他操作。

---

## 📁 文件路径

```
src/autospider/cli.py
```

---

## 📑 函数目录

### 🚀 核心命令
- `run` - 运行 Agent
- `collect` - 收集详情页 URL
- `generate-config` - 生成配置文件

---

## 🚀 核心功能

### run 命令

运行 Agent 执行自动化任务。

```bash
autospider run \
  --start-url https://example.com \
  --task "收集商品价格信息" \
  --target-text "价格" \
  --max-steps 20 \
  --output-dir output
```

### collect 命令

收集详情页 URL。

```bash
autospider collect \
  --list-url https://example.com/list \
  --task "收集商品详情页链接" \
  --explore-count 3 \
  --output-dir output
```

### generate-config 命令

生成配置文件。

```bash
autospider generate-config \
  --list-url https://example.com/list \
  --task "收集商品详情页链接" \
  --explore-count 3 \
  --output-dir output
```

---

## 💡 特性说明

### Typer 集成

使用 Typer 提供现代化的 CLI 体验。

### Rich 输出

使用 Rich 提供美观的命令行输出。

---

## 🔧 使用示例

### 运行 Agent

```bash
# 基本使用
autospider run \
  --start-url https://example.com \
  --task "收集商品价格信息" \
  --target-text "价格"

# 完整参数
autospider run \
  --start-url https://example.com \
  --task "收集商品价格信息" \
  --target-text "价格" \
  --max-steps 20 \
  --output-dir output \
  --headless
```

### 收集 URL

```bash
# 基本使用
autospider collect \
  --list-url https://example.com/list \
  --task "收集商品详情页链接"

# 完整参数
autospider collect \
  --list-url https://example.com/list \
  --task "收集商品详情页链接" \
  --explore-count 5 \
  --max-pages 40 \
  --target-url-count 400 \
  --output-dir output
```

---

## 📚 命令参考

### run 命令

| 参数 | 类型 | 说明 |
|------|------|------|
| `--start-url` | string | 起始 URL |
| `--task` | string | 任务描述 |
| `--target-text` | string | 目标提取文本 |
| `--max-steps` | int | 最大步骤数 |
| `--output-dir` | string | 输出目录 |
| `--headless` | bool | 是否无头模式 |

### collect 命令

| 参数 | 类型 | 说明 |
|------|------|------|
| `--list-url` | string | 列表页 URL |
| `--task` | string | 任务描述 |
| `--explore-count` | int | 探索详情页数量 |
| `--max-pages` | int | 最大翻页次数 |
| `--target-url-count` | int | 目标 URL 数量 |
| `--output-dir` | string | 输出目录 |

---

*最后更新: 2026-01-08*
