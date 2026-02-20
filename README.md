# AutoSpider

AutoSpider 是一个基于 `LangGraph + Playwright + SoM(Set-of-Mark)` 的纯视觉网页采集 Agent。
它可以自动完成列表页探索、详情页 URL 收集、字段规则归纳（XPath）以及批量抽取。

## 核心能力

- **全自然语言对话交互**：支持 `chat-pipeline` 命令，通过多轮 AI 对话自动澄清需求、生成采集字段模型并一键运行流水线。
- **自动登录与状态记忆**：内置异常检测与悬浮提示横幅，遇到需登录或验证码等情况实时等待用户人工接管处理，并自动持久化 Cookie 会话状态（`.auth/`）。
- **智能目标分析系统**：自动识别列表页“目标详情链接”，自主学习全站导航步骤（含验证与提取强健稳定的多重属性 XPath），大大降低规则配置门槛。
- **大规模并发流水线**：支持端到端并行生产者-消费者采集流水线 `pipeline-run`；内置支持 `memory / file / redis` 队列多通道及字段内省自动纠错恢复机制。
- **核心组件分拆**：
  - 各类流水线极解耦支持独立阶段模式：`generate-config` + `batch-collect`（两阶段超稳并支持原生进度/Redis断点续爬）。
  - 给定 URL 直接解析抽取器 `field-extract` 支持完整的 "探索 -> 验证 -> 批量提取" 生命周期运行。

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

### 0) 全自然语言多轮交互执行（最新推荐）

无需繁琐手写字段规则配置，通过对话直接引导程序自动完成爬虫开发及运行全过程：

```bash
# 可以 -r 带上核心需求，也可以不带参数由系统通过控制台发起追问
autospider chat-pipeline -r "帮我采集 example 网站的公告列表，字段只需包含标题和发布时间"
```

### 1) 一键收集详情 URL（独立动作、推荐分析时使用）

```bash
autospider collect-urls \
  --list-url "https://example.com/list" \
  --task "收集招标公告详情页 URL" \
  --explore-count 3 \
  --target-url-count 20
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
  --target-url-count 20 \
  --output output
```

### 3) 并行流水线（列表采集 + 字段抽取）

```bash
autospider pipeline-run \
  --list-url "https://example.com/list" \
  --task "采集详情页中的标题和发布时间" \
  --fields-file fields.json \
  --target-url-count 20 \
  --mode memory \
  --consumer-concurrency 3 \
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

- `.auth/*`：框架在浏览器中全自动或人工辅助后记录的相关登录会话凭据记录。
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
