# AutoSpider

AutoSpider 是一个基于 `LangGraph + Playwright + SoM(Set-of-Mark)` 的纯视觉网页采集 Agent。
它可以自动完成列表页探索、详情页 URL 收集、字段规则归纳（XPath）以及批量抽取，并通过独创的“智能规划引擎”实现大型复杂站点的全自动全站爬取。

## 🌟 核心能力

- **全自然语言对话交互 (`chat-pipeline`)**：只需输入一句话，系统会通过多轮 AI 澄清对话 (`TaskClarifier`) 自动对齐需求、推断目标及提取字段配置，随后一键启动完整的数据采集流水线。
- **智能规划引擎 (Planning Agent)**：面对多分类/多频道的复杂站点，内置 `TaskPlanner` 能够利用 SoM 视觉大模型技术，自主分析页面导航结构，将大型爬取任务自动拆解为多个独立稳定的子任务，彻底攻克规模化采集难题。
- **强健稳定的全自动 XPath 归纳**：不仅自主学习全站导航步骤，还运用多种策略（深度绑定 `id`, `class`, `data-*` 等语义属性）归纳并优选最稳定的多重属性 XPath。并内置“内省与自适应挽救机制（Salvage Mechanism）”，自动修正极少数提取异常的字段。
- **自适应网络拦截与人工接管 (Guard)**：全新的网络与行为监控机制，遇到需要登录、人机验证等情况会自动弹出系统横幅，实时等待用户接管处理，并自动持久化 Cookie 与会话状态（`.auth/`）。
- **极速并行生产者-消费者流水线**：将页面图遍历与底层数据处理解耦，支持端到端的并发流水线（`pipeline-run`）。内置 `memory` / `file` / `redis` 多通道消息队列机制，并支持断点续爬及动态爬取速率控制。
- **全生命周期阶段拆分**：
  - 二阶段极稳模式：`generate-config`（探索与规则生成） + `batch-collect`（按规则极速获取）。
  - 给定 URL 列表直接抽取：`field-extract` 支持 "探索 -> 验证 -> 批量提取" 生命周期运行。

## ⚙️ 运行要求

- Python `>=3.10`
- 已安装浏览器驱动（Playwright Chromium）

## 📦 安装

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

## 🛠 配置（`.env`）

先复制 `.env.example` 为 `.env`，再按需修改。
最小可用配置示例（按代码实际读取的变量名）：

```env
BAILIAN_API_KEY=your_api_key
BAILIAN_API_BASE=https://api.siliconflow.cn/v1
BAILIAN_MODEL=qwen3.5-plus

# 规划器专用模型（如需单独指定更强大的视觉模型）
# PLANNER_API_KEY=your_planner_key
# PLANNER_MODEL=qwen-vl-plus

HEADLESS=false
PIPELINE_MODE=memory
```

*注意：`pipeline-run` 默认模式来自 `PIPELINE_MODE`，若未配置 Redis 请务必使用 `memory` 模式。*

## 🚀 快速开始

### 0) 全自然语言多轮交互执行（最推荐 🎉）

无需手写繁琐配置或分析结构，支持“大体量”站点全自动智能拆解与并发采集：

```bash
# --execution-mode 支持 auto/single/multi
# multi 模式会自动启动 Planning Agent 进行全站频道推断拆解
autospider chat-pipeline -r "帮我采集 example 网站所有分类的公告列表，字段包含标题和发布时间" --execution-mode auto
```

### 1) 一键收集详情 URL（独立动作）

```bash
autospider collect-urls \
  --list-url "https://example.com/list" \
  --task "收集招标公告详情页 URL" \
  --explore-count 3 \
  --target-url-count 20
```

### 2) 两阶段模式（解耦生成规则与批量采集模式）

```bash
# 阶段1：探索并生成配置
autospider generate-config --list-url "https://example.com/list" --task "收集详情页 URL" --output output

# 阶段2：按配置自动分页批量采集
autospider batch-collect --config-path output/collection_config.json --target-url-count 20 --output output
```

### 3) 传统并行流水线（列表采集 + 字段抽取并行）

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

### 4) 根据已有 URL 列表直接抽取

```bash
autospider field-extract \
  --urls-file output/urls.txt \
  --fields-file fields.json \
  --output output
```

## 📂 核心项目结构

```text
src/autospider/
├── cli.py                 # 命令行入口 (chat-pipeline / pipeline-run 等)
├── common/                # 通用基础设施 (LLM 对话澄清 TaskClarifier / 设置面板 Guard 等)
├── crawler/               # 采集引擎 (包含强大的 planner 规划模块，支持子任务拆分)
├── field/                 # 字段工厂 (包含多策略 XPath 归纳与容错挽救机制)
├── pipeline/              # 并行调度 (生产者-消费者高并发核心架构)
└── prompts/               # AI Prompt 模板与提示词工程优化
```

## 🧪 开发与测试

```bash
pip install -e ".[dev]"
pytest
```
