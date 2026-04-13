<a href="https://deepwiki.com/pinkllo/autospider"><img src="https://deepwiki.com/badge.svg" alt="Ask DeepWiki"></a>

# AutoSpider

English | **[中文](README.md)**

AutoSpider is a pure-vision web crawling agent built with `LangGraph + Playwright + SoM (Set-of-Mark)`.
It can automatically discover detail links, infer highly stable and reusable XPath patterns, extract structured fields, and utilize a **Planning Agent** to decompose and crawl large-scale, complex multi-category websites.

## 🌟 Key Features

- **Natural Language Interaction (`chat-pipeline`)**: Define what you want in plain text. A multi-turn AI clarification system (`TaskClarifier`) automatically infers the target URL, data fields, and optimal crawling strategy, then launches the full pipeline with a single command.
- **Smart Planning Agent**: Employs SoM visual recognition to analyze complex site navigation. It automatically breaks down massive, multi-category websites into independent, stable sub-tasks (`multi` mode) for scalable crawling.
- **Robust XPath Generation & Error Salvage**: Infers comprehensive multi-attribute XPath selectors (binding `id`, `class`, `data-*`). A built-in "salvage mechanism" automatically fixes and repairs field extraction errors gracefully on the fly.
- **Non-intrusive Guard & Session Memory**: When captchas or logins interrupt, the crawler pauses seamlessly, popping a unified browser banner for human intervention. Session status is saved incrementally inside `.auth/`.
- **Redis-only runtime contract**: the public CLI and pipeline contract are now intentionally narrowed to Redis-only. Unified graph orchestration, resumability, adaptive rate control, and concurrent execution remain, but the day-to-day entrypoints are `doctor`, `chat-pipeline`, `resume`, and `db-init`.

## 🏗️ System Architecture

AutoSpider uses a LangGraph-based state graph architecture centered on the `chat-pipeline` entry path. The developer entrypoint is now: run `doctor` first, then use `chat-pipeline` for the main path; `resume` and `db-init` stay as operational commands. In the current implementation, chat-originated work always enters planning before concurrent dispatch:

```mermaid
graph LR
  A["🚀 CLI Entry"] --> B["🔀 route_entry<br/>Entry Router"]
  B --> C["💬 Chat Branch"]
  B --> D["🔧 Pipeline Branch"]
  B --> E["🛠️ Capability Nodes"]
  B --> F["🧠 Multi-Task Planning"]

  C --> G["📤 Finalization"]
  D --> G
  E --> G
  F --> G
  G --> H["🔴 End"]
```

> 📊 For a detailed node-level flowchart with feature descriptions, see [`output/graph/main_graph.mmd`](main_graph.mmd)

### Execution Routes

| Entry Mode | Execution Route | Description |
|:---|:---|:---|
| `chat_pipeline` | chat_clarify → chat_history_match → chat_review_task → chat_prepare_execution_handoff → plan_node → multi_dispatch_subgraph → aggregate_node | 💬 AI-driven multi-turn dialog, then planning-first concurrent execution |

## ⚙️ Requirements

- Python `>=3.10`
- Playwright Chromium

## 📦 Installation

```bash
pip install -e .
playwright install chromium
```

Optional extras:
```bash
pip install -e ".[redis]"   # Redis queue support
pip install -e ".[db]"      # Database support
pip install -e ".[spider]"  # Scrapy integration
pip install -e ".[dev]"     # Testing / formatting / type checking
```

## 🛠 Configuration (`.env`)

Copy `.env.example` to `.env` and set values.
Minimal working setup:

```env
BAILIAN_API_KEY=your_api_key
BAILIAN_API_BASE=https://api.siliconflow.cn/v1
BAILIAN_MODEL=qwen3.5-plus

# Dedicated Vision-Model Planner (Optional)
# PLANNER_API_KEY=your_planner_key
# PLANNER_MODEL=qwen-vl-plus

REDIS_ENABLED=true
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
HEADLESS=false
PIPELINE_MODE=redis
```

*Note: the public CLI now assumes a Redis-only runtime contract; run `autospider doctor` first to check database, Redis, and graph checkpoint prerequisites.*

## 🚀 Quick Start

### 0) Run environment checks first

```bash
autospider doctor
```

### 1) AI-Driven Interactive Crawling (Recommended 🎉)

Chat your way to data. The system clarifies the task, optionally reuses historical tasks, asks for final review, then enters planning and concurrent subtask dispatch automatically:

```bash
# Automatically clarifies the task and enters the planning-first chat pipeline
autospider chat-pipeline -r "Collect articles across all categories from example.com and extract titles & dates"
```

### 2) Resume an interrupted run

```bash
autospider resume --thread-id "<thread_id>"
```

## 📂 Core Project Structure

```text
src/autospider/
├── cli.py                     # CLI entry point (doctor / chat-pipeline / resume / db-init)
├── cli_runtime.py             # CLI runtime wiring and doctor helpers
├── graph/                     # LangGraph state graph orchestration layer
│   ├── main_graph.py          #   Main graph construction & routing logic
│   ├── runner.py              #   GraphRunner unified execution entry
│   ├── state.py               #   GraphState state definition
│   ├── types.py               #   Entry mode / status enums
│   └── nodes/                 #   Graph node implementations
│       ├── entry_nodes.py     #     Entry routing / param normalization / dialog clarification
│       ├── capability_nodes.py#     Capability execution nodes
│       └── shared_nodes.py    #     Shared finalization nodes (Artifact/Summary/Finalize)
├── common/                    # Shared infrastructure
│   ├── config.py              #   Global configuration management
│   ├── browser/               #   BrowserSession management
│   ├── channel/               #   Redis-only queue/runtime adapters
│   ├── llm/                   #   LLM dialog clarification (TaskClarifier) & decision engine
│   ├── som/                   #   Set-of-Mark visual annotation engine
│   ├── storage/               #   Persistence & Redis management
│   └── utils/                 #   Utilities (fuzzy search / delay / templates)
├── crawler/                   # Crawling engine
│   ├── base/                  #   Base collector (BaseCollector)
│   ├── collector/             #   URL collector & config generator
│   ├── explore/               #   Exploration engine (config gen / URL collection)
│   ├── batch/                 #   Batch collector
│   ├── planner/               #   TaskPlanner smart planning engine
│   └── checkpoint/            #   Breakpoint resumption & rate control
├── field/                     # Field extraction factory
│   ├── field_extractor.py     #   Core field extraction logic
│   ├── xpath_pattern.py       #   Multi-strategy XPath inference engine
│   ├── field_decider.py       #   Field decision & salvage mechanism
│   ├── batch_field_extractor.py#  Batch field extraction
│   └── batch_xpath_extractor.py#  Batch XPath extraction
├── pipeline/                  # Pipeline execution
│   ├── aggregator.py          #   ResultAggregator result merger
│   ├── worker.py              #   SubTaskWorker isolated subtask worker
│   └── runner.py              #   Pipeline producer-consumer runner
├── output/                    # Output processing
└── prompts/                   # AI Prompt engineering templates
    ├── task_clarifier.yaml    #   Dialog clarification prompts
    ├── planner.yaml           #   Task planning prompts
    ├── url_collector.yaml     #   URL collection prompts
    ├── field_extractor.yaml   #   Field extraction prompts
    ├── xpath_pattern.yaml     #   XPath inference prompts
    └── decider.yaml           #   Field decision prompts
```

## 🧪 Development & Testing

```bash
pip install -e ".[redis,db,dev]"
autospider doctor
pytest -m smoke -q
pytest tests/e2e -m e2e -q
```

`pytest tests/e2e -m e2e -q` is the only maintained E2E entrypoint now. When the runtime dependencies or infra are unavailable, the suite exits through explicit `skip`s instead of failing during `pytest configure`. See [`tests/e2e/README.md`](tests/e2e/README.md) for the full end-to-end setup notes.

## 📄 License

MIT License
