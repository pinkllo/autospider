# AutoSpider

AutoSpider 是一个基于 `LangGraph + Playwright + SoM(Set-of-Mark)` 的纯视觉网页采集 Agent。  
它可以自动完成列表页探索、详情页 URL 收集、字段规则归纳（XPath）以及批量抽取。

## 核心能力

- 自动探索列表页，识别“目标详情链接”
- 自动学习导航步骤与公共 XPath，减少手写规则
- 支持两阶段采集：`generate-config` + `batch-collect`
- 支持端到端并行流水线：`pipeline-run`
- 字段抽取支持“探索 -> 验证 -> 批量提取”
- 支持 `memory / file / redis` 三种 URL 通道模式
- 支持断点续爬（本地进度 + Redis 队列）

## 运行要求

- Python `>=3.10`
- 已安装浏览器驱动（Playwright Chromium）

## 安装

```bash
pip install -e .
playwright install chromium
```

可选依赖：

```bash
pip install -e ".[redis]"   # Redis 队列能力
pip install -e ".[db]"      # 数据库相关能力
pip install -e ".[spider]"  # Scrapy 相关能力
pip install -e ".[dev]"     # 测试/格式化/类型检查
```

## 配置（`.env`）

先复制 `.env.example` 为 `.env`，再按需修改。

最小可用配置示例（按代码实际读取的变量名）：

```env
BAILIAN_API_KEY=your_api_key
BAILIAN_API_BASE=https://api.siliconflow.cn/v1
BAILIAN_MODEL=qwen3.5-plus

HEADLESS=false
PIPELINE_MODE=memory
```

Redis 模式示例：

```env
PIPELINE_MODE=redis
REDIS_ENABLED=true
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_KEY_PREFIX=autospider:urls
```

注意：

- `pipeline-run` 默认模式来自 `PIPELINE_MODE`，代码默认值为 `redis`。如果未准备 Redis，请显式使用 `--mode memory` 或在 `.env` 中设置 `PIPELINE_MODE=memory`。
- 当前代码读取 `BAILIAN_*` 变量；如果你沿用 `.env.example` 里的 `AIPING_*` 前缀，需要改名或同时设置两套变量。

## 字段定义文件示例（`fields.json`）

```json
[
  {
    "name": "title",
    "description": "文章标题",
    "required": true,
    "data_type": "text",
    "example": "示例标题"
  },
  {
    "name": "publish_date",
    "description": "发布时间",
    "required": true,
    "data_type": "text"
  }
]
```

## 快速开始

### 1) 一键收集详情 URL（推荐先跑通）

```bash
autospider collect-urls \
  --list-url "https://example.com/list" \
  --task "收集招标公告详情页 URL" \
  --explore-count 3
```

### 2) 两阶段模式（更稳）

```bash
# 阶段1：探索并生成配置
autospider generate-config \
  --list-url "https://example.com/list" \
  --task "收集招标公告详情页 URL" \
  --output output

# 阶段2：按配置批量采集
autospider batch-collect \
  --config-path output/collection_config.json \
  --output output
```

### 3) 并行流水线（列表采集 + 字段抽取）

```bash
autospider pipeline-run \
  --list-url "https://example.com/list" \
  --task "采集详情页中的标题和发布时间" \
  --fields-file fields.json \
  --mode memory \
  --output output
```

### 4) 对已有 URL 列表做字段抽取

```bash
autospider field-extract \
  --urls-file output/urls.txt \
  --fields-file fields.json \
  --output output
```

## 主要输出文件

- `output/collection_config.json`：导航步骤、详情 XPath、分页 XPath 等配置
- `output/collected_urls.json`：结构化 URL 收集结果
- `output/urls.txt`：纯 URL 列表（一行一个）
- `output/spider.py`：自动生成的详情页爬虫脚本
- `output/extraction_config.json`：字段提取规则配置
- `output/extraction_result.json`：字段探索/验证结果
- `output/extracted_items.json`：字段抽取结果
- `output/pipeline_extracted_items.jsonl`：流水线实时抽取结果
- `output/pipeline_summary.json`：流水线运行摘要

## 项目结构（简要）

```text
src/autospider/
├── cli.py                 # 命令行入口
├── common/                # 配置、浏览器、SoM、通道、存储等基础设施
├── crawler/               # 列表页探索、URL 收集、断点续爬
├── field/                 # 字段探索、XPath 归纳、批量抽取
├── pipeline/              # 并行流水线编排
└── prompts/               # LLM Prompt 模板
```

## 开发与测试

```bash
pip install -e ".[dev]"
pytest
```

## 文档入口

- 项目文档总览：`docs/README.md`
- CLI 说明：`docs/cli.py.md`
- 流水线说明：`docs/pipeline/runner.py.md`
