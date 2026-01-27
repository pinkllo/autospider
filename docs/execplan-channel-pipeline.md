# 可配置 URL 通道与流水线并行采集

本 ExecPlan 是一个持续更新的执行计划文档，必须遵循仓库根目录 `PLANS.md` 的要求进行维护。

## Purpose / Big Picture

完成本变更后，用户可以通过配置选择三种 URL 传输通道（内存、文件、Redis），并在列表页采集进行时同步启动详情页字段抽取流水线。可观察到的结果是：列表页 URL 在产生的同时就被详情页抽取消费，且模式可通过配置切换。

## Progress

- [x] (2026-01-22 01:10Z) 编写并落地 URL 通道抽象与三种实现（内存、文件、Redis），含工厂方法与基础类型。
- [x] (2026-01-22 01:20Z) 将 BaseCollector 接入 URL 通道发布逻辑，保持现有行为兼容。
- [x] (2026-01-22 01:35Z) 新增流水线编排器，支持并行生产与消费，并输出流水线结果。
- [x] (2026-01-22 01:40Z) 将配置中加入 PipelineConfig 并完成默认参数接入。
- [x] (2026-01-22 01:55Z) 增加 CLI 入口与函数入口，支持命令行与库调用。

## Surprises & Discoveries

- Observation: 为避免覆盖批量抽取结果，流水线输出独立 JSONL 文件更安全。
  Evidence: 批量抽取现有输出固定为 `batch_extraction_result.json` 与 `extracted_items.json`，重复覆盖会丢失中间结果。

## Decision Log

- Decision: 新增 `autospider.common.channel` 包作为 URL 通道抽象的落脚点。
  Rationale: 通道需要被 crawler 与 field 复用，放入 common 层可以降低耦合。
  Date/Author: 2026-01-22 / Codex

- Decision: 流水线结果以 JSONL 追加文件输出，而不是复用 BatchXPathExtractor 的固定输出文件。
  Rationale: 流水线是持续消费，避免反复覆盖同名结果文件，保持现有批量抽取输出兼容。
  Date/Author: 2026-01-22 / Codex

- Decision: File 通道只负责消费 urls.txt，publish 保持为 no-op。
  Rationale: 采集侧已通过进度持久化追加 urls.txt，重复写入会增加 I/O 与去重成本。
  Date/Author: 2026-01-22 / Codex

- Decision: 提供 `pipeline-run` CLI 命令并在 `autospider.__init__` 导出 `run_pipeline`。
  Rationale: 便于命令行与 Python 调用两种入口并存，符合用户“CLI 与函数入口”的需求。
  Date/Author: 2026-01-22 / Codex

## Outcomes & Retrospective

已完成三类 URL 通道的实现与工厂创建，新增流水线编排器实现列表采集与详情抽取并行执行，并在配置中加入 PipelineConfig 供模式切换。现有批量抽取输出保持不变，流水线新增 JSONL 输出以支持持续写入。

## Context and Orientation

当前 URL 收集入口在 `src/autospider/crawler/base/base_collector.py`，采集时会把 URL 追加到 `self.collected_urls` 并在断点恢复逻辑中写入 `output/urls.txt`。字段抽取逻辑在 `src/autospider/field` 下，`BatchFieldExtractor` 负责探索/分析公共 XPath，`BatchXPathExtractor` 负责基于公共 XPath 的批量提取。配置位于 `src/autospider/common/config.py`，需在此新增 PipelineConfig 以选择通道模式。

本方案新增“URL 通道（URL channel）”概念：一个可被生产者发布 URL、被消费者按批拉取 URL 的抽象接口。三种实现分别是内存队列（同进程）、文件尾随（urls.txt）与 Redis Stream 队列。

## Plan of Work

首先在 `src/autospider/common/channel/` 新建通道抽象及实现：定义 `URLTask`（包含 URL 以及可选的 ACK/FAIL 回调），并提供 `URLChannel` 的 `publish` 与 `fetch` 接口。实现内存通道、文件通道（读取 urls.txt 与 cursor 文件）、Redis 通道（封装 `RedisQueueManager`）。提供 `create_url_channel` 工厂函数以根据配置选择通道，并返回 Redis 通道所需的 `RedisQueueManager` 以供采集侧复用。

随后在 `src/autospider/crawler/base/base_collector.py` 中注入通道发布逻辑：新增 `url_channel` 参数与 `_publish_url` 方法，在发现新 URL 时优先写入通道；当通道未配置时保持现有 Redis 推送行为不变。为避免未使用 Redis 却仍创建 Redis 管理器，调整 `_init_redis_manager` 仅在没有通道且未显式传入管理器时初始化。

然后新增流水线编排器 `src/autospider/pipeline/runner.py`。它同时启动 URL 采集（生产者）和字段提取（消费者），消费者先用少量 URL 生成公共 XPath，再持续消费剩余 URL 并写入 JSONL 结果文件。流水线根据 `config.pipeline.mode` 创建通道，实现内存/文件/Redis 三种切换。

最后在 `src/autospider/common/config.py` 增加 `PipelineConfig` 并在 `Config` 中挂载，提供模式选择与基础参数（内存队列大小、文件轮询间隔、消费批量大小与超时等）。

## Concrete Steps

在 `d:\autospider` 下执行以下操作：

1) 新增通道模块文件：`src/autospider/common/channel/base.py`、`memory_channel.py`、`file_channel.py`、`redis_channel.py`、`factory.py`、`__init__.py`。

2) 修改 `src/autospider/common/config.py`，添加 `PipelineConfig` 并在 `Config` 中挂载。

3) 修改 `src/autospider/crawler/base/base_collector.py`，加入通道发布逻辑和可选 `redis_manager` 参数。

4) 新增流水线编排器：`src/autospider/pipeline/runner.py` 与 `src/autospider/pipeline/__init__.py`。

预期能看到新增文件与配置字段，运行时可通过配置选择通道模式。

## Validation and Acceptance

至少完成以下可观察验证之一（无需实际访问网站即可验证结构）：

- 运行 `python -m autospider` 不报模块导入错误，且 `from autospider.pipeline import run_pipeline` 可被导入。
- 使用一个本地 URL 列表文件模拟 file 通道时，消费者能够从 `output/urls.txt` 中读取并输出 JSONL 结果文件（内容可为空，但流程可跑通）。

若环境允许访问目标网站，可运行流水线函数并观察：

- 列表页采集仍在进行时，`pipeline_extracted_items.jsonl` 持续增长。
- 切换 `PIPELINE_MODE` 为 `memory` / `file` / `redis` 后流程仍可启动。

## Idempotence and Recovery

以上变更均为增量添加，可重复执行。若流水线输出文件已存在，继续运行会追加写入 JSONL 文件；如需全量重跑，可手动清理 `output/pipeline_extracted_items.jsonl` 与 `output/pipeline_summary.json`。

## Artifacts and Notes

示例（预期新增的导入路径）：

    from autospider.common.channel import create_url_channel
    from autospider.pipeline import run_pipeline

## Interfaces and Dependencies

新增接口与类型：

- 在 `src/autospider/common/channel/base.py` 定义：

    class URLChannel(ABC):
        async def publish(self, url: str) -> None: ...
        async def fetch(self, max_items: int, timeout_s: float | None) -> list[URLTask]: ...
        async def close(self) -> None: ...

    @dataclass
    class URLTask:
        url: str
        ack: Callable[[], Awaitable[None]] | None
        fail: Callable[[str], Awaitable[None]] | None

- 在 `src/autospider/pipeline/runner.py` 定义：

    async def run_pipeline(
        list_url: str,
        task_description: str,
        fields: list[FieldDefinition],
        output_dir: str = "output",
        headless: bool = False,
    ) -> dict:
        ...

变更说明（2026-01-22）：新建 ExecPlan 文件，记录总体方案与计划，便于后续按里程碑实施。

变更说明（2026-01-22）：完成通道实现、BaseCollector 接入、流水线编排器与配置扩展，并更新进度与决策记录。

变更说明（2026-01-22）：新增 CLI 与函数入口，补充计划进度与决策记录。
