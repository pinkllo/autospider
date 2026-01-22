# AutoSpider - Vision-based SoM Browser Agent

[English](./README_en.md) | [简体中文](./README.md)

AutoSpider is a vision-based browser automation agent built on LangGraph, Playwright, and Multi-modal LLMs. By simulating human visual recognition and interaction habits, AutoSpider understands webpages like a human, performs complex navigation/filtering, and automatically generates robust crawler scripts.

## 🚀 Core Features

### Set-of-Mark (SoM) Visual Annotation
- **Smart Ancestor Detection**: Automatically identifies clickable parent containers, avoiding trivial child elements for more precise interaction.
- **Multi-dimensional Visibility Check**: Combines viewport detection, Z-index analysis, and multi-point sampling to ensure only truly visible elements are marked.
- **Robust XPath Candidates**: Built-in heuristic algorithm generates stable locators by priority (ID > TestID > Aria-Label > Text > Relative Path).

### Intelligent Field Extraction
- **Multi-strategy Extraction**: Supports field extraction based on LLM vision, XPath matching, and fuzzy search.
- **Common XPath Distillation**: Analyzes multiple detail pages to automatically extract the most stable common XPath patterns.
- **Auto-validation**: Built-in verification process ensures the universality and accuracy of generated XPath patterns across different pages.

### Autonomous URL Batch Collection
- **Two-phase Workflow**: Supports "Explore & Config -> Batch Collect" decoupled process, ideal for large-scale, long-term tasks.
- **Guided Navigation**: LLM observes the page and automatically clicks filters (e.g., industry, status) based on natural language instructions.
- **Multi-strategy Pagination**: Combines LLM vision and rule-based fallback to handle various pagination controls (numbers, next buttons, etc.).
- **Checkpointing**: Integrated Redis persistence allows resuming from interruptions.
- **Adaptive Rate Control**: Dynamically adjusts frequency based on response status to balance efficiency and stability.

### Intelligent Crawler Generation
- **One-click Scrapy Spider**: Automatically generates professional `Scrapy` + `scrapy-playwright` scripts based on distilled XPaths and navigation patterns.
- **High-concurrency Architecture**: Leverages Scrapy's asynchronous engine for high-efficiency large-scale crawling.
- **Self-healing Patterns**: Generated scripts include interaction patterns learned during exploration for basic fault tolerance.

## 🛠️ Installation

```bash
# Create and activate conda environment
conda create -n autospider python=3.10 -y
conda activate autospider

# Install package in editable mode
pip install -e .

# Install Playwright browsers
playwright install chromium
```

## ⚙️ Configuration

### 1. Environment Variables (.env)

Copy `.env.example` to `.env` and fill in your LLM provider details:

```bash
cp .env.example .env
```

**Key Settings:**
- `API_KEY`: Multi-modal LLM API Key
- `API_BASE`: API base URL
- `MODEL`: Multi-modal model to use (recommended: `Qwen3-VL-235B-A22B-Instruct`)

### 2. Crawling Behavior

To simulate human behavior and avoid anti-bot detection, adjust these in `.env`:

```env
ACTION_DELAY_BASE=1.0
ACTION_DELAY_RANDOM=0.5
PAGE_LOAD_DELAY=1.5
SCROLL_DELAY=0.5
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
```

> [!TIP]
> All default values are managed in `src/autospider/common/config.py` using Pydantic.

## 📖 Usage Guide

### 1. URL Batch Collection (Recommended Phase Workflow) ⭐

This is the flagship feature. We recommend the two-phase approach.

#### Phase 1: Explore & Generate Config (`generate-config`)

The system opens a browser, explores the site based on your task, analyzes patterns, and saves a configuration file.

```bash
autospider generate-config \
  --list-url "https://example.com/list" \
  --task "Collect all bidding announcements related to transportation" \
  --explore-count 3
```

#### Phase 2: Batch Collection (`batch-collect`)

Run high-efficiency collection using the generated config with resume support.

```bash
autospider batch-collect \
  --config-path output/collection_config.json \
  --headless
```

### 2. One-click URL Collection (`collect-urls`)

For a quick start, use the all-in-one command:

```bash
autospider collect-urls \
  --list-url "https://xxx.gov.cn/list" \
  --task "Collect all bidding announcements" \
  --explore-count 3
```

### 3. Parallel Pipeline (list + detail) (`pipeline-run`) ⭐

The pipeline runs list collection and detail extraction concurrently. It supports three modes:
- `memory`: in-process queue (fastest, no persistence)
- `file`: reads `output/urls.txt` (local & resumable)
- `redis`: Redis Stream queue (production parallelism)

**Fields definition example (fields.json)**

```json
[
  {"name": "title", "description": "announcement title"},
  {"name": "winner", "description": "winning bidder"},
  {"name": "project_no", "description": "project number"}
]
```

**Run example**

```bash
autospider pipeline-run \
  --list-url "https://example.com/list" \
  --task "Collect award results and extract title/winner/project number" \
  --fields-file output/fields.json \
  --mode redis \
  --headless
```

**Outputs**
- `output/pipeline_extracted_items.jsonl`: JSONL output appended per URL
- `output/pipeline_summary.json`: summary stats and errors


## 📂 Project Structure

```
autospider/
├── src/autospider/
│   ├── common/                 # Common modules
│   │   ├── browser/           # Browser automation
│   │   ├── channel/           # URL channels (memory/file/redis)
│   │   ├── som/               # Set-of-Mark system
│   │   ├── storage/           # Persistence (Redis)
│   │   ├── llm/               # LLM adapters & prompts
│   │   └── config.py          # Config management
│   ├── crawler/               # Crawling core (explore, batch, collector, checkpoint)
│   ├── field/                 # Field extraction (detail page auto-recognition)
│   ├── pipeline/              # Concurrent pipeline orchestration
│   ├── cli.py                 # CLI entry point
│   └── __main__.py            # Module entry
├── prompts/                   # Independent prompt templates
├── tests/                     # Unit tests
└── output/                    # Default output directory
```

## 📝 Prerequisites

- Python 3.10+
- Redis Server (Optional, for checkpointing)
- Scrapy & scrapy-playwright (To run generated scripts)
- Vision-capable Multi-modal LLM API (e.g., Qwen2-VL, GLM-4V)

## 📄 License

MIT License
