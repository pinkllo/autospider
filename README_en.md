# AutoSpider

AutoSpider is a pure-vision web crawling agent built with `LangGraph + Playwright + SoM (Set-of-Mark)`.
It can discover detail links from list pages, infer reusable XPath patterns, and extract structured fields at scale.

## Features

- Visual list-page exploration with LLM decisions
- Auto-generated navigation steps and common XPath rules
- Two-stage crawling workflow: `generate-config` + `batch-collect`
- End-to-end concurrent pipeline: `pipeline-run`
- Field extraction workflow: explore -> validate -> batch extract
- URL channel backends: `memory / file / redis`
- Resume support via local progress and Redis queue

## Requirements

- Python `>=3.10`
- Playwright Chromium:

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

## Environment (`.env`)

Copy `.env.example` to `.env` and set values.

Minimal setup (actual variable names used in code):

```env
BAILIAN_API_KEY=your_api_key
BAILIAN_API_BASE=https://api.siliconflow.cn/v1
BAILIAN_MODEL=qwen3.5-plus
HEADLESS=false
PIPELINE_MODE=memory
```

Notes:

- `pipeline-run` falls back to `PIPELINE_MODE`; code default is `redis`.
- If Redis is not available, use `--mode memory` or set `PIPELINE_MODE=memory`.
- Current code reads `BAILIAN_*`; if you copied `AIPING_*` from `.env.example`, rename or provide both.

## `fields.json` Example

```json
[
  {"name": "title", "description": "Article title", "required": true, "data_type": "text"},
  {"name": "publish_date", "description": "Publish date", "required": true, "data_type": "text"}
]
```

## Quick Start

One-shot URL collection:

```bash
autospider collect-urls \
  --list-url "https://example.com/list" \
  --task "Collect detail page URLs" \
  --explore-count 3
```

Two-stage URL collection:

```bash
autospider generate-config --list-url "https://example.com/list" --task "Collect detail URLs" --output output
autospider batch-collect --config-path output/collection_config.json --output output
```

Concurrent pipeline (URL collection + field extraction):

```bash
autospider pipeline-run \
  --list-url "https://example.com/list" \
  --task "Extract title and publish date from detail pages" \
  --fields-file fields.json \
  --mode memory \
  --output output
```

Field extraction from existing URL list:

```bash
autospider field-extract \
  --urls-file output/urls.txt \
  --fields-file fields.json \
  --output output
```

## Key Outputs

- `output/collection_config.json`
- `output/collected_urls.json`
- `output/urls.txt`
- `output/spider.py`
- `output/extraction_config.json`
- `output/extraction_result.json`
- `output/extracted_items.json`
- `output/pipeline_extracted_items.jsonl`
- `output/pipeline_summary.json`

## Docs

- `docs/README.md`
- `docs/cli.py.md`
- `docs/pipeline/runner.py.md`
