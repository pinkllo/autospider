# AutoSpider

AutoSpider is a pure-vision web crawling agent built with `LangGraph + Playwright + SoM (Set-of-Mark)`.
It can automatically discover detail links, infer highly stable and reusable XPath patterns, extract structured fields, and utilize a **Planning Agent** to decompose and crawl large-scale, complex multi-category websites.

## 🌟 Key Features

- **Natural Language Interaction (`chat-pipeline`)**: Define what you want in plain text. A multi-turn AI clarification system automatically infers the target URL, data fields, and optimal crawling strategy.
- **Smart Planning Agent**: Employs SoM visual recognition to analyze complex site navigation. It automatically breaks down massive, multi-category websites into independent, stable sub-tasks (`multi` mode) for scalable crawling.
- **Robust XPath Generation & Error Salvage**: Infers comprehensive multi-attribute XPath selectors (binding `id`, `class`, `data-*`). A built-in "salvage mechanism" automatically fixes and repairs field extraction errors gracefully on the fly.
- **Non-intrusive Guard & Session Memory**: When captchas or logins interrupt, the crawler pauses seamlessly, popping a unified browser banner for human intervention. Session status is saved incrementally inside `.auth/`.
- **High-Performance Producer-Consumer Pipeline**: Graph traversal runs decoupled from data extraction. Supports concurrent consumers bounded by flexible queues (`memory`, `file`, `redis`), equipped with rate limiting and breakpoint resumption.
- **Decoupled Workflows**: Run full-scale, end-to-end extraction, or split them into deterministic stages: `generate-config` + `batch-collect`.

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
pip install -e ".[redis]"
pip install -e ".[db]"
pip install -e ".[spider]"
pip install -e ".[dev]"
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

HEADLESS=false
PIPELINE_MODE=memory
```

*Note: Ensure `PIPELINE_MODE=memory` if Redis is not configured.*

## 🚀 Quick Start

### 0) AI-Driven Interactive Crawling (Recommended 🎉)

Chat your way to data. The system automatically reasons and coordinates tasks via single or multi-channel strategies:

```bash
# --execution-mode supports auto/single/multi. "multi" builds a global site plan via Planning Agent.
autospider chat-pipeline -r "Collect articles across all categories from example.com and extract titles & dates" --execution-mode auto
```

### 1) URL Collection

```bash
autospider collect-urls \
  --list-url "https://example.com/list" \
  --task "Collect detail page URLs" \
  --explore-count 3 \
  --target-url-count 20
```

### 2) Two-Stage Configuration & Collection (Stable Mode)

```bash
autospider generate-config --list-url "https://example.com/list" --task "Collect detail URLs" --output output
autospider batch-collect --config-path output/collection_config.json --target-url-count 20 --output output
```

### 3) Concurrent Processing Pipeline

```bash
autospider pipeline-run \
  --list-url "https://example.com/list" \
  --task "Extract title and publish date from detail pages" \
  --fields-file fields.json \
  --mode memory \
  --consumer-concurrency 3 \
  --output output
```

### 4) Pure Extraction From Given URLs

```bash
autospider field-extract \
  --urls-file output/urls.txt \
  --fields-file fields.json \
  --output output
```

## 📂 Core Project Structure

```text
src/autospider/
├── cli.py                 # CLI Interface
├── common/                # Base infrastructure (TaskClarifier, Guard, auth)
├── crawler/               # Crawler Engine featuring the visual Planning Agent
├── field/                 # Field rules inference, multi-XPath fallback & Salvage mechanics
├── pipeline/              # Producer-Consumer parallelism orchestration
└── prompts/               # Centralized Prompt Engineering templates
```
