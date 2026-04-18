# 05 · 防腐机制（配置样例）

所有配置在阶段 5 `commit[5.1]` 统一落地。本文档给出**可直接复制**的配置文件样例，确保重构后的架构不会再次退化。

---

## 1. `pyproject.toml` · `[tool.ruff]`（升级版）

替换当前 `pyproject.toml` 中现有的 `[tool.ruff]` 段：

```toml
[tool.ruff]
line-length = 100
target-version = "py310"
src = ["src", "tests"]
exclude = [
    ".venv", ".git", "__pycache__", "build", "dist",
    "src/autospider/prompts",              # YAML 资产
    "tests/benchmark/mock_site",
]

[tool.ruff.lint]
select = [
    "E",   "W",   # pycodestyle
    "F",          # pyflakes（未用、重定义）
    "I",          # isort
    "UP",         # pyupgrade
    "B",          # bugbear
    "C4",         # comprehensions
    "SIM",        # simplify
    "TID",        # tidy-imports（禁止相对导入跨越过深）
    "TCH",        # type-checking 分离
    "PL",         # pylint 子集
    "C90",        # 复杂度
    "N",          # 命名
    "RUF",
]
ignore = [
    "E501",       # 交给 black
    "PLR0913",    # 参数个数（DI 构造函数易超）
]

[tool.ruff.lint.mccabe]
max-complexity = 10

[tool.ruff.lint.pylint]
max-statements = 50
max-branches = 12
max-args = 8

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["PLR2004", "S101"]          # 测试允许魔法数与 assert
"src/autospider/platform/shared_kernel/**" = ["PLR0911"]

[tool.ruff.lint.flake8-tidy-imports]
ban-relative-imports = "all"              # 禁止相对 import

[tool.ruff.lint.isort]
known-first-party = ["autospider"]
```

**关键约束**：
- `max-complexity = 10`：函数圈复杂度上限
- `max-statements = 50`：单函数语句数上限
- `ban-relative-imports`：禁止相对 import，强制绝对 import，便于跨层追踪

---

## 2. `pyproject.toml` · `[tool.mypy]`（升级版）

```toml
[tool.mypy]
python_version = "3.10"
warn_return_any = true
warn_unused_configs = true
warn_unused_ignores = true
warn_redundant_casts = true
no_implicit_optional = true
strict_equality = true
ignore_missing_imports = true      # 第三方库缺 stubs 不阻塞
pretty = true

# 核心领域层严格模式
[[tool.mypy.overrides]]
module = [
    "autospider.contexts.*.domain.*",
    "autospider.platform.shared_kernel.*",
]
strict = true
disallow_untyped_defs = true
disallow_any_explicit = false      # 允许 Any（pydantic 里有些场景必要）

# application 层半严格
[[tool.mypy.overrides]]
module = [
    "autospider.contexts.*.application.*",
]
disallow_untyped_defs = true
check_untyped_defs = true

# infrastructure / composition 渐进（短期宽松）
[[tool.mypy.overrides]]
module = [
    "autospider.contexts.*.infrastructure.*",
    "autospider.composition.*",
    "autospider.interface.*",
]
disallow_untyped_defs = false
check_untyped_defs = true

# 测试宽松
[[tool.mypy.overrides]]
module = "tests.*"
disallow_untyped_defs = false
check_untyped_defs = false
```

---

## 3. `.importlinter`（项目根）

```ini
[importlinter]
root_package = autospider

# ==================== 契约 1：分层架构 ====================
[importlinter:contract:layers]
name = Layered architecture
type = layers
layers =
    autospider.interface
    autospider.composition
    autospider.contexts
    autospider.platform
ignore_imports =
    # 允许 platform.shared_kernel 被任何层用
    autospider.** -> autospider.platform.shared_kernel

# ==================== 契约 2：Context 相互独立 ====================
[importlinter:contract:contexts-isolated]
name = Bounded contexts do not import each other
type = independence
modules =
    autospider.contexts.planning
    autospider.contexts.collection
    autospider.contexts.experience
    autospider.contexts.chat

# ==================== 契约 3：Domain 层纯净 ====================
[importlinter:contract:domain-pure-planning]
name = Planning domain is pure
type = forbidden
source_modules =
    autospider.contexts.planning.domain
forbidden_modules =
    langgraph
    playwright
    redis
    sqlalchemy
    openai
    loguru
    langchain
    requests
    httpx

[importlinter:contract:domain-pure-collection]
name = Collection domain is pure
type = forbidden
source_modules =
    autospider.contexts.collection.domain
forbidden_modules =
    langgraph
    playwright
    redis
    sqlalchemy
    openai
    loguru
    langchain
    requests
    httpx

[importlinter:contract:domain-pure-experience]
name = Experience domain is pure
type = forbidden
source_modules =
    autospider.contexts.experience.domain
forbidden_modules =
    langgraph
    playwright
    redis
    sqlalchemy
    openai
    loguru
    langchain

[importlinter:contract:domain-pure-chat]
name = Chat domain is pure
type = forbidden
source_modules =
    autospider.contexts.chat.domain
forbidden_modules =
    langgraph
    playwright
    redis
    sqlalchemy
    openai
    loguru
    langchain

# ==================== 契约 4：Application 不依赖 Infrastructure ====================
[importlinter:contract:app-no-infra]
name = Application layer does not import infrastructure
type = forbidden
source_modules =
    autospider.contexts.planning.application
    autospider.contexts.collection.application
    autospider.contexts.experience.application
    autospider.contexts.chat.application
forbidden_modules =
    autospider.contexts.planning.infrastructure
    autospider.contexts.collection.infrastructure
    autospider.contexts.experience.infrastructure
    autospider.contexts.chat.infrastructure

# ==================== 契约 5：Interface 不直接依赖 Contexts ====================
[importlinter:contract:interface-via-composition]
name = Interface must not directly import contexts
type = forbidden
source_modules =
    autospider.interface
forbidden_modules =
    autospider.contexts
```

**运行**：`lint-imports`（安装 `import-linter` 后可用）。

---

## 4. `.pre-commit-config.yaml`

```yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-toml
      - id: check-added-large-files
        args: ["--maxkb=500"]
      - id: check-merge-conflict
      - id: detect-private-key

  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.5.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format

  - repo: https://github.com/psf/black
    rev: 24.4.2
    hooks:
      - id: black

  - repo: local
    hooks:
      - id: mypy
        name: mypy (domain + application strict)
        entry: mypy
        language: system
        types: [python]
        pass_filenames: false
        args: [src/autospider]

      - id: import-linter
        name: import-linter (layered + bounded contexts)
        entry: lint-imports
        language: system
        types: [python]
        pass_filenames: false

      - id: file-size-gate
        name: block new .py files larger than 500 lines
        language: system
        entry: python scripts/_gate_file_size.py
        types: [python]
        pass_filenames: true
```

**对应脚本** `scripts/_gate_file_size.py`（单文件行数守门）：

```python
"""Fail pre-commit if a staged .py file exceeds 500 lines (excluding tests)."""
import sys
from pathlib import Path

LIMIT = 500
EXEMPT_PREFIX = ("tests/", "src/autospider/prompts/")

failed: list[tuple[str, int]] = []
for path in sys.argv[1:]:
    if path.endswith(".py") and not any(path.startswith(p) for p in EXEMPT_PREFIX):
        n = sum(1 for _ in Path(path).open(encoding="utf-8", errors="ignore"))
        if n > LIMIT:
            failed.append((path, n))

if failed:
    for p, n in failed:
        print(f"❌ {p} has {n} lines (limit {LIMIT}). Please split.")
    sys.exit(1)
```

---

## 5. CI 流水线（GitHub Actions 示例）

`.github/workflows/ci.yml`：

```yaml
name: CI

on:
  push:
    branches: [main, refactor/**]
  pull_request:

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  lint-type-test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python: ["3.10", "3.11"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}
      - name: Install
        run: |
          python -m pip install -U pip
          pip install -e ".[dev,redis,db]"
      - name: Ruff
        run: ruff check src tests
      - name: Black
        run: black --check src tests
      - name: Mypy
        run: mypy src/autospider
      - name: Import-linter
        run: lint-imports
      - name: Deptry
        run: deptry src
      - name: Pytest (smoke + contracts + unit)
        run: |
          pytest -m smoke -q
          pytest tests/contracts -q
          pytest tests/contexts tests/platform tests/composition tests/interface -q

  e2e:
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    services:
      redis:
        image: redis:7-alpine
        ports: ['6379:6379']
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_PASSWORD: postgres
        ports: ['5432:5432']
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install
        run: |
          python -m pip install -U pip
          pip install -e ".[all]"
          playwright install --with-deps chromium
      - name: Migrate
        env:
          AUTOSPIDER_DB_URL: postgresql+psycopg://postgres:postgres@localhost:5432/postgres
        run: alembic upgrade head
      - name: E2E
        env:
          AUTOSPIDER_REDIS_URL: redis://localhost:6379/0
          AUTOSPIDER_DB_URL: postgresql+psycopg://postgres:postgres@localhost:5432/postgres
        run: pytest tests/e2e -m e2e -q
```

**关键设计**：
- **lint + type + smoke + contracts + 分层单测**：每次 push 都跑，<3 min
- **E2E**：仅 PR 跑，启动 Redis + Postgres service，完整 Playwright 环境

---

## 6. `deptry` 配置（`pyproject.toml`）

```toml
[tool.deptry]
extend_exclude = [
    "tests/",
    "refactor/",
    "scripts/",
    "src/autospider/prompts/",
]
ignore = [
    "DEP002",              # unused package in pyproject（由于 optional-extras）
]

[tool.deptry.package_module_name_map]
"langgraph-checkpoint-redis" = "langgraph_checkpoint_redis"
"opencv-python-headless" = "cv2"
```

---

## 7. PR 模板（`.github/pull_request_template.md`）

```markdown
## 摘要
<!-- 本 PR 做了什么变更 -->

## 架构影响
- [ ] 新增/删除 Bounded Context
- [ ] 修改 `contexts/*/domain/` 下的聚合/值对象
- [ ] 新增/删除 Domain Event
- [ ] 修改 Redis key 规范（bump version?）
- [ ] 修改 DB schema（含 Alembic migration?）
- [ ] 修改 `ResultEnvelope` / 产物格式
- [ ] 以上都没有

## 验证
- [ ] `scripts/verify.ps1` 本地绿
- [ ] `pytest tests/contracts -q` 快照无破坏（或已更新并说明原因）
- [ ] CI 绿

## ADR
若涉及架构决策变更，请附上对应 `refactor/adr/NNNN-*.md` 的链接。

## 回滚方案
<!-- 如何回滚本 PR -->
```

---

## 8. CODEOWNERS（示例）

`.github/CODEOWNERS`：

```
# 架构骨架与跨层规约
/src/autospider/platform/shared_kernel/  @architect-team
/refactor/                               @architect-team
/.importlinter                           @architect-team
/pyproject.toml                          @architect-team

# 各 Context 由领域负责人维护
/src/autospider/contexts/planning/       @planning-owner
/src/autospider/contexts/collection/     @collection-owner
/src/autospider/contexts/experience/     @experience-owner
/src/autospider/contexts/chat/           @chat-owner

# Persistence / Messaging 变更需要 SRE review
/src/autospider/platform/persistence/    @sre-team
/src/autospider/platform/messaging/      @sre-team
```

单人项目可忽略 CODEOWNERS；团队化后再启用。

---

## 9. ADR 模板

`refactor/adr/NNNN-<topic>.md`：

```markdown
# NNNN · <决策标题>

- 状态：Proposed / Accepted / Superseded-by-NNNN
- 日期：YYYY-MM-DD
- 决策者：@user1, @user2

## 背景

<!-- 什么问题驱动了本次决策？先前的方案是什么？为何不够用？ -->

## 决策

<!-- 一句话结论 + 3~5 点关键理由 -->

## 后果

- 正面：...
- 负面：...
- 触发的后续工作：...

## 替代方案

<!-- 考虑过但被否决的方案与否决理由 -->
```

**必写 ADR 的场景**：
1. 新增/删除 Bounded Context
2. 引入新的外部依赖（尤其持久化、消息、LLM provider）
3. 修改 Redis key 规范（bump 版本）
4. 修改 `ResultEnvelope` 或产物目录结构
5. 调整 `import-linter` 契约

---

## 10. 度量指标看板（持续跟踪）

在 `refactor/_generated/metrics.md`（由 `scripts/measure.py` 定期生成）记录：

| 指标 | 工具 | 目标 |
|---|---|---|
| 总 LoC（src） | `tokei` 或 `python -c "..."` | ↓ 20%+ |
| Python 文件数 | 统计 | 稳定 |
| 单文件行数 p95 | 自写脚本 | ≤ 400 |
| 圈复杂度 p95 | `radon cc src -a` | ≤ 10 |
| mypy 错误数 | `mypy src/autospider 2>&1 \| grep error \| wc -l` | = 0 |
| 死代码行数（vulture ≥80） | `vulture src --min-confidence 80` | = 0 |
| import-linter 违规 | `lint-imports` | = 0 |
| 测试数 / 覆盖率 | `pytest --cov` | ↑ |

**建议**：每周或每阶段末跑一次，存 `refactor/_generated/metrics-YYYYMMDD.md`，便于追踪趋势。

---

## 11. 文化约束（书面化，CI 无法强制但 review 时执行）

1. **Boy Scout Rule**：每个 PR 允许且鼓励 ≤50 行的"顺手整理"（重命名变量、提取常量等），不改变行为。
2. **路径命名禁令**：新增文件不允许出现 `_temp`、`_legacy`、`workaround`、`hack`、`misc`、`util_v2` 等含糊命名。
3. **单函数行数**：超过 80 行或圈复杂度 >10 必须在 PR 描述中说明原因。
4. **跨 Context 通讯**：代码评审中若看到 `from autospider.contexts.A import ...` 出现在 `contexts.B` 下，直接 block（即便 `import-linter` 未触发）。
5. **Redis key 拼接**：评审中看到 `f"autospider:..."` 字符串直接 block，必须用 `keys.py` 的函数。
6. **打补丁修复**：紧急 fix 允许 `fix:` commit，但 3 个工作日内必须转成合规的 PR（带测试），否则回滚。
