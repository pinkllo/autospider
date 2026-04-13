# E2E 闭环测试

根 README 才是开发入口权威说明。推荐顺序是先运行：

```bash
autospider doctor
pytest -m smoke -q
pytest tests/e2e -m e2e -q
```

`pytest tests/e2e -m e2e -q` 是当前唯一维护的 E2E 入口。若 PostgreSQL、Redis、`redis` Python 依赖或本地运行时工作目录不可用，suite 会显式 `skip`，而不是在 `pytest configure` 阶段硬失败。

这套测试以 `GraphRunner.invoke/resume` 为主入口，覆盖 `chat_pipeline -> planning -> multi_dispatch -> aggregate` 的真实图执行链路。测试只比较最终交付结果：

- `merged_results.jsonl`
- `merged_summary.json`

不会把任务树、数据库中间态、内部 `_subtask_*` 字段纳入 golden 比较。

## 前置条件

需要先安装项目和测试依赖：

```bash
pip install -e ".[redis,db,dev]"
playwright install chromium
```

运行前需要可用的 PostgreSQL 和 Redis：

- PostgreSQL：作为 E2E 主数据库，供历史任务、运行记录和最终持久化使用
- Redis：只用于 graph checkpoint
- Playwright Chromium：用于真实浏览器流程

默认情况下，E2E 会自动加载仓库根目录下的 `.env.e2e`。

当前推荐内容：

```env
AUTOSPIDER_E2E_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/autospider_e2e_test
AUTOSPIDER_E2E_REDIS_URL=redis://127.0.0.1:6380/15
```

如果你想临时覆盖，也可以直接设置环境变量。

CMD 示例：

```bash
set AUTOSPIDER_E2E_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/autospider_e2e_test
set AUTOSPIDER_E2E_REDIS_URL=redis://127.0.0.1:6380/15
```

如果使用 PowerShell：

```powershell
$env:AUTOSPIDER_E2E_DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5432/autospider_e2e_test"
$env:AUTOSPIDER_E2E_REDIS_URL="redis://127.0.0.1:6380/15"
```

如果不提供 `AUTOSPIDER_E2E_REDIS_URL`，fixture 会尝试从本机 `PATH` 中启动临时 `redis-server`。
数据库会在每个 case 前后执行 `init_db(reset=True)`，因此强烈建议始终使用显式测试库。
E2E 运行时会优先使用仓库内 `.tmp/e2e-runtime/` 作为工作目录，并把临时文件收口到该工作区下。

## 目录约定

这两个文件负责子任务 E：

- `test_graph_e2e.py`：主 E2E 参数化测试入口
- `README.md`：运行说明

测试会依赖同目录下其他子任务产出的资产：

- `conftest.py`：环境初始化、PostgreSQL reset、Redis fixture、mock site fixture
- `mock_site/`：本地模拟站点
- `cases/`：`GraphE2ECase` 清单
- `golden/`：标准答案
- `harness/`：`GraphRunner.invoke/resume` 驱动器

`test_graph_e2e.py` 当前约定寻找以下 fixture：

- `graph_e2e_driver` 或 `graph_harness` 或 `e2e_harness`
- `graph_e2e_cases` 或 `e2e_cases` 或 `cases_by_id`
- `mock_site_base_url` 或 `base_url` 或 `mock_site_url` 或 `mock_site_server`

如果 case 不通过 fixture 暴露，测试也会回退读取 `tests.e2e.cases` 模块中的 `CASE_BY_ID` 或 `ALL_CASES`。

## 运行命令

运行全部 E2E：

```bash
pytest tests/e2e -m e2e -q
```

只跑单个 case：

```bash
pytest tests/e2e -m e2e -k graph_same_page_variant -q
```

查看详细日志：

```bash
pytest tests/e2e -m e2e -vv -s
```

## 断言口径

每个 case 都会严格断言：

- `GraphResult.status == "success"`
- `merged_results.jsonl` 与对应 golden 完全一致
- `merged_summary.json` 中的 `merged_items`、`unique_urls` 与 case manifest 完全一致
- 产物文件必须真实存在

records 比较时只保留业务字段：

- `url`
- `title`
- `publish_date`
- `budget`
- `attachment_url`

golden 记录中的 `{{base_url}}` 会在运行时替换成 mock site 的实际地址。

summary 比较时只保留：

- `merged_items`
- `unique_urls`

## 首批 case

- `graph_all_categories`
- `graph_same_page_variant`
- `graph_direct_list_pagination_dedupe`
