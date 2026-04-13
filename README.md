<a href="https://deepwiki.com/pinkllo/autospider"><img src="https://deepwiki.com/badge.svg" alt="Ask DeepWiki"></a>

# AutoSpider

**[English](README_en.md)** | 中文

AutoSpider 是一个基于 `LangGraph + Playwright + SoM(Set-of-Mark)` 的纯视觉网页采集 Agent。
它通过 planning-first 的 chat 主链路，将自然语言需求澄清、历史任务复用、分组规划、多子任务执行和结果聚合串成一条可恢复的公开工作流。

## 🌟 核心能力

- **Planning-first 对话主链路 (`chat-pipeline`)**：只需输入一句话，系统会先执行多轮 AI 澄清 (`TaskClarifier`)、历史任务匹配、人工 review，再进入 planning 与 multi-dispatch。
- **显式分组采集语义**：当任务被澄清为 `group_by=category` 时，系统会以页面上实际发现的分类为分组单位，`per_group_target_count` 表示“每个分类抓多少条”，而不是全局总数。
- **分类事实来自页面与子任务上下文**：分类集合由 planner 根据页面事实发现；进入执行期后，分类字段来自 subtask 的 `scope` / `fixed_fields`，而不是到详情页再猜测分类。
- **强健稳定的全自动 XPath 归纳**：不仅自主学习全站导航步骤，还运用多种策略（深度绑定 `id`, `class`, `data-*` 等语义属性）归纳并优选最稳定的多重属性 XPath。并内置"内省与自适应挽救机制（Salvage Mechanism）"，自动修正极少数提取异常的字段。
- **自适应网络拦截与人工接管 (Guard)**：全新的网络与行为监控机制，遇到需要登录、人机验证等情况会自动弹出系统横幅，实时等待用户接管处理，并自动持久化 Cookie 与会话状态（`.auth/`）。
- **语义身份驱动的历史复用**：历史任务复用不再只看 URL 或文案，系统会基于归一化后的 strategy payload 与字段集合生成 `semantic_signature`，用于对齐历史记录与当前意图。

## 🏗️ 系统架构

AutoSpider 采用基于 LangGraph 的状态图架构。当前公开 CLI 只有 3 个命令：`chat-pipeline`、`resume`、`db-init`。其中真正的采集入口只有 `chat-pipeline`，并且 chat 发起的任务固定先进入 planning，再进入分发监控与世界模型反馈，最终才聚合结果：

```mermaid
graph LR
  A["autospider chat-pipeline"] --> B["chat_clarify"]
  B --> C["chat_history_match"]
  C --> D["chat_review_task"]
  D --> E["chat_prepare_execution_handoff"]
  E --> F["plan_node"]
  F --> G["multi_dispatch_subgraph"]
  G --> H["monitor_dispatch_node"]
  H --> I["update_world_model_node"]
  I --> J{"需要重规划?"}
  J -->|是| K["plan_strategy_node"]
  K --> F
  J -->|否| L["aggregate_node"]
  L --> M["finalize"]
  N["autospider resume"] --> O["恢复中断线程"]
  P["autospider db-init"] --> Q["初始化 PostgreSQL schema"]
```

> 📊 完整的带功能描述的节点级流程图请参见 [`main_graph.mmd`](main_graph.mmd)

### 分支路线说明

| 入口模式          | 执行路线                                                                 | 功能说明                                  |
| :---------------- | :----------------------------------------------------------------------- | :---------------------------------------- |
| `chat_pipeline` | chat_clarify → chat_history_match → chat_review_task → chat_prepare_execution_handoff → plan_node → multi_dispatch_subgraph → monitor_dispatch_node → update_world_model_node → (按需重规划) → aggregate_node | 💬 正式主链路：自然语言澄清后进入 planning-first，并允许基于反馈重规划 |

> `collect_urls`、`generate_config`、`batch_collect`、`field_extract`、`multi_pipeline` 等旧能力仅保留为内部实现细节，不再作为 README 对外入口承诺。

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
# SILICON_PLANNER_API_KEY=your_planner_key
# SILICON_PLANNER_MODEL=qwen-vl-plus

REDIS_ENABLED=true
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
HEADLESS=false
PIPELINE_MODE=redis
```

*注意：`chat-pipeline` 中若未显式传入 `--mode`，默认模式来自 `PIPELINE_MODE`。当前代码中的可选执行后端值为 `memory` / `file` / `redis`。如果已安装 Redis 相关依赖并完成配置，可再切换到 `redis`。*

## 🚀 快速开始

### 0) 先做环境自检

```bash
autospider doctor
```

### 1) 全自然语言多轮交互执行（最推荐 🎉）

无需手写繁琐配置或分析结构。系统会先澄清任务、按需复用历史任务、执行 review，再进入 planning 与并发子任务调度：

```bash
# 自动澄清需求，并进入 planning-first 的 chat 主链路
autospider chat-pipeline -r "帮我采集 example 网站页面上所有分类下的专业列表，每个分类抓 3 条，字段包含专业名称和所属分类"
```

### 分组采集语义

- `group_by=category`：按页面上发现的分类拆分子任务，而不是把“分类”当作详情页字段临时猜测。
- `per_group_target_count`：每个分类的目标条数；若页面最终发现 5 个分类，系统会按 5 个分组分别执行。
- `category_discovery_mode=auto`：默认由页面事实自动发现分类；只有显式指定 `requested_categories` 时才会进入手工限定分组。
- 分类字段写入结果时来自 subtask 的 `scope` / `fixed_fields`，用于覆盖详情页里可能缺失或不稳定的分类展示。

### 1) 恢复中断执行

```bash
autospider resume --thread-id "<thread_id>"
```

## 📂 核心项目结构

```text
src/autospider/
├── cli.py                     # 命令行入口 (doctor / chat-pipeline / resume / db-init)
├── cli_runtime.py             # CLI 运行时装配与 doctor 自检 helper
├── graph/                     # LangGraph 状态图编排层（主图/恢复/汇总适配）
│   ├── main_graph.py          #   主图构建与路由逻辑
│   ├── runner.py              #   GraphRunner 统一执行入口
│   ├── state.py               #   GraphState 状态定义
│   ├── types.py               #   入口模式/状态枚举
│   └── nodes/                 #   图节点实现
│       ├── entry_nodes.py     #     入口路由 / 参数归一化 / 对话澄清
│       ├── capability_nodes.py#     各能力执行节点
│       └── shared_nodes.py    #     共享收尾节点 (Artifact/Summary/Finalize)
├── common/                    # 过渡期通用基础设施（后续逐步拆分，不再新增业务模块）
│   ├── config.py              #   全局配置管理
│   ├── browser/               #   BrowserRuntimeSession 主生命周期抽象（BrowserSession 兼容层）
│   ├── channel/               #   Pipeline 后端通道 (memory / file / redis)
│   ├── llm/                   #   LLM 对话澄清 (TaskClarifier) 与决策器
│   ├── som/                   #   Set-of-Mark 视觉标注引擎
│   ├── storage/               #   持久化存储与 Redis 管理
│   └── utils/                 #   工具函数 (模糊搜索 / 延迟 / 模板)
├── crawler/                   # 采集引擎
│   ├── base/                  #   基础采集器 (BaseCollector)
│   ├── collector/             #   URL 收集与配置生成器
│   ├── explore/               #   探索引擎 (配置生成 / URL 收集)
│   ├── batch/                 #   批量采集器
│   ├── planner/               #   TaskPlanner 智能任务规划引擎
│   └── checkpoint/            #   断点续爬与速率控制
├── field/                     # 字段工厂
│   ├── field_extractor.py     #   字段提取器核心逻辑
│   ├── xpath_pattern.py       #   多策略 XPath 归纳引擎
│   ├── field_decider.py       #   字段决策与挽救机制
│   ├── batch_field_extractor.py#  批量字段提取
│   └── batch_xpath_extractor.py#  批量 XPath 提取
├── pipeline/                  # 单子任务执行流水线
│   ├── aggregator.py          #   ResultAggregator 结果聚合器
│   ├── worker.py              #   SubTaskWorker 子任务执行单元
│   └── runner.py              #   Pipeline 生产者-消费者运行器
├── output/                    # 输出处理
└── prompts/                   # AI Prompt 模板与提示词工程
    ├── task_clarifier.yaml    #   对话澄清提示词
    ├── planner.yaml           #   任务规划提示词
    ├── url_collector.yaml     #   URL 收集提示词
    ├── field_extractor.yaml   #   字段提取提示词
    ├── xpath_pattern.yaml     #   XPath 归纳提示词
    └── decider.yaml           #   字段决策提示词
```

> 当前约束：
> 对外开发入口已收口为 `autospider doctor`、`chat-pipeline`、`resume`、`db-init`；
> 历史兼容入口 `BrowserSession`、`TaskRegistry`、`FieldXPathRegistry` 与旧 service facade 已移除。

## 🧪 开发与测试

```bash
pip install -e ".[redis,db,dev]"
autospider doctor
pytest -m smoke -q
pytest tests/e2e -m e2e -q
```

其中 `pytest tests/e2e -m e2e -q` 是当前唯一维护的 E2E 入口；运行依赖或基础设施不可用时，会以显式 `skip` 收口，而不是在 `pytest configure` 阶段硬失败。更完整的闭环说明见 [`tests/e2e/README.md`](tests/e2e/README.md)。

## 📄 License

MIT License
